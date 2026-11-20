"""Публикация событий и проверка доступности RabbitMQ."""

import asyncio
import logging
from typing import Protocol

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractConnection, AbstractExchange
from aio_pika.exceptions import (
    AMQPError,
    AuthenticationError,
    ChannelInvalidStateError,
    DeliveryError,
    IncompatibleProtocolError,
    ProbableAuthenticationError,
    PublishError,
)
from aiormq.exceptions import ConnectionNotAllowed

from app.schemas.lesson_events import PublishedLessonEvent

log = logging.getLogger(__name__)

EXCHANGE = "wa.events"
_PUBLISH_TIMEOUT_SECONDS = 2.0
_PREPARE_ATTEMPTS = 3
_PREPARE_TIMEOUT_SECONDS = 0.5
_RETRY_DELAY_SECONDS = 0.1
_TRANSIENT_ERRORS = (OSError, EOFError, StopAsyncIteration, ChannelInvalidStateError)
_BROKER_ERRORS = (*_TRANSIENT_ERRORS, AMQPError, ValueError)


class BrokerProbe(Protocol):
    """Проверка доступности брокера для readiness."""

    async def ping(self) -> bool:
        """True, если брокер отвечает."""
        ...


class UnconfiguredBrokerProbe:
    """Проверка для контекста, собранного без брокера."""

    async def ping(self) -> bool:
        return False


class EventPublisher(Protocol):
    async def publish(self, event: PublishedLessonEvent) -> None:
        """Отправить событие после commit и учесть ошибки транспорта."""
        ...


class RabbitMQBroker:
    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: AbstractConnection | None = None
        self._channel: AbstractChannel | None = None
        self._setup_lock = asyncio.Lock()

    async def _declare_exchange(self) -> AbstractExchange:
        async with self._setup_lock:
            connection = self._connection
            if connection is None or connection.is_closed or not connection.connected.is_set():
                connection = await aio_pika.connect(self._url)
                self._connection = connection
                self._channel = None

            channel = self._channel
            if channel is None or channel.is_closed:
                channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
                self._channel = channel
            return await channel.declare_exchange(
                EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            )

    async def _prepare_exchange(self) -> AbstractExchange:
        for attempt in range(1, _PREPARE_ATTEMPTS):
            try:
                async with asyncio.timeout(_PREPARE_TIMEOUT_SECONDS):
                    return await self._declare_exchange()
            except (
                AuthenticationError,
                ProbableAuthenticationError,
                IncompatibleProtocolError,
                ConnectionNotAllowed,
            ):
                raise
            except _TRANSIENT_ERRORS:
                log.debug("RabbitMQ preparation failed on attempt %s", attempt)
                await asyncio.sleep(_RETRY_DELAY_SECONDS)

        async with asyncio.timeout(_PREPARE_TIMEOUT_SECONDS):
            return await self._declare_exchange()

    async def ping(self) -> bool:
        try:
            # DeclareExchange is an AMQP round trip even when the channel already exists.
            await self._declare_exchange()
        except _BROKER_ERRORS:
            return False
        return True

    async def publish(self, event: PublishedLessonEvent) -> None:
        message = aio_pika.Message(
            body=event.model_dump_json().encode("utf-8"),
            content_type="application/json",
            message_id=str(event.event_id),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        publish_called = False
        try:
            async with asyncio.timeout(_PUBLISH_TIMEOUT_SECONDS):
                exchange = await self._prepare_exchange()
                # Once publish is called, a lost confirm can mean the broker accepted the message.
                publish_called = True
                await exchange.publish(
                    message, routing_key=f"timetable.{event.event_type}", mandatory=True
                )
        except _BROKER_ERRORS as error:
            if isinstance(error, PublishError):
                result = "unroutable"
            elif isinstance(error, DeliveryError):
                result = "rejected"
            elif publish_called:
                result = "unconfirmed"
            else:
                result = "not sent"
            log.error(
                "RabbitMQ publication %s (%s): event_type=%s event_id=%s lesson_id=%s",
                result,
                type(error).__name__,
                event.event_type,
                event.event_id,
                event.payload.lesson_id,
            )

    async def aclose(self) -> None:
        if self._connection is not None:
            await self._connection.close()
