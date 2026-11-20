import asyncio
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import aio_pika
import pytest
from aio_pika.exceptions import AuthenticationError, PublishError
from pamqp.commands import Basic

from app import broker
from app.broker import RabbitMQBroker
from app.enums.lessons import LessonStatus
from app.schemas.lesson_events import LessonCancelledPayload, LessonEvent

_URL = "amqp://user:secret@rabbitmq/"


@pytest.fixture
def event() -> LessonEvent[LessonCancelledPayload]:
    now = datetime(2026, 11, 30, 3, tzinfo=UTC)
    return LessonEvent[LessonCancelledPayload](
        event_type="LessonCancelled",
        occurred_at=now,
        payload=LessonCancelledPayload(
            lesson_id=uuid4(),
            group_id=uuid4(),
            instructor_id=uuid4(),
            starts_at=now,
            ends_at=now.replace(hour=4),
            previous_status=LessonStatus.CONFIRMED,
            reason=None,
        ),
    )


def _connection() -> tuple[MagicMock, MagicMock, MagicMock]:
    exchange = MagicMock(publish=AsyncMock())
    channel = MagicMock(is_closed=False, declare_exchange=AsyncMock(return_value=exchange))
    connection = MagicMock(is_closed=False, channel=AsyncMock(return_value=channel))
    connection.connected.is_set.return_value = True
    connection.close = AsyncMock()
    return connection, channel, exchange


async def test_publish_retries_preparation_and_sets_amqp_properties(
    event: LessonEvent[LessonCancelledPayload], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, channel, exchange = _connection()
    channel.declare_exchange.side_effect = [TimeoutError(), exchange]
    connect = AsyncMock(side_effect=[ConnectionRefusedError(), connection])
    monkeypatch.setattr(aio_pika, "connect", connect)
    monkeypatch.setattr(broker, "_RETRY_DELAY_SECONDS", 0)

    adapter = RabbitMQBroker(_URL)
    await adapter.publish(event)

    assert connect.await_count == 2
    connect.assert_awaited_with(_URL)
    connection.channel.assert_awaited_once_with(publisher_confirms=True, on_return_raises=True)
    assert channel.declare_exchange.await_count == 2
    channel.declare_exchange.assert_awaited_with(
        "wa.events", aio_pika.ExchangeType.TOPIC, durable=True
    )
    exchange.publish.assert_awaited_once()
    args, kwargs = exchange.publish.await_args
    (message,) = args
    assert kwargs == {"routing_key": "timetable.LessonCancelled", "mandatory": True}
    assert message.body.decode() == event.model_dump_json()
    assert message.content_type == "application/json"
    assert message.message_id == str(event.event_id)
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT


@pytest.mark.parametrize(
    ("error", "attempts"), [(ConnectionRefusedError, 3), (AuthenticationError, 1)]
)
async def test_preparation_failure_logs_one_final_error(
    event: LessonEvent[LessonCancelledPayload],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: type[Exception],
    attempts: int,
) -> None:
    connect = AsyncMock(side_effect=error("private connection details"))
    monkeypatch.setattr(aio_pika, "connect", connect)
    monkeypatch.setattr(broker, "_RETRY_DELAY_SECONDS", 0)

    await RabbitMQBroker(_URL).publish(event)

    assert connect.await_count == attempts
    errors = [record.message for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "not sent" in errors[0]
    assert str(event.event_id) in errors[0]
    assert str(event.payload.lesson_id) in errors[0]
    assert "private connection details" not in errors[0]


async def test_publish_does_not_repeat_after_confirm_timeout(
    event: LessonEvent[LessonCancelledPayload],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection, _, exchange = _connection()
    cancelled = asyncio.Event()

    async def wait_for_confirm(*_args: object, **_kwargs: object) -> None:
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setattr(aio_pika, "connect", AsyncMock(return_value=connection))
    monkeypatch.setattr(broker, "_PUBLISH_TIMEOUT_SECONDS", 0.05)
    exchange.publish.side_effect = wait_for_confirm

    await RabbitMQBroker(_URL).publish(event)

    exchange.publish.assert_awaited_once()
    assert cancelled.is_set()
    assert [record.message.split()[2] for record in caplog.records] == ["unconfirmed"]


async def test_unroutable_publication_is_logged_without_retry(
    event: LessonEvent[LessonCancelledPayload],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection, _, exchange = _connection()
    monkeypatch.setattr(aio_pika, "connect", AsyncMock(return_value=connection))
    returned = Basic.Return(reply_code=312, reply_text="NO_ROUTE")
    exchange.publish.side_effect = PublishError(MagicMock(delivery=returned), returned)

    await RabbitMQBroker(_URL).publish(event)

    exchange.publish.assert_awaited_once()
    assert len(caplog.records) == 1
    assert "unroutable" in caplog.records[0].message


async def test_ping_checks_amqp_and_reconnects_after_connection_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, first_channel, first_exchange = _connection()
    second, second_channel, second_exchange = _connection()
    connect = AsyncMock(side_effect=[ConnectionRefusedError(), first, second])
    monkeypatch.setattr(aio_pika, "connect", connect)
    adapter = RabbitMQBroker(_URL)
    connect.assert_not_awaited()

    assert not await adapter.ping()
    assert await adapter.ping()
    first_channel.declare_exchange.side_effect = TimeoutError()
    assert not await adapter.ping()
    assert first_channel.declare_exchange.await_count == 2
    first.connected.is_set.return_value = False
    assert await adapter.ping()
    second_channel.declare_exchange.assert_awaited_once()
    assert connect.await_count == 3
    first_exchange.publish.assert_not_awaited()
    second_exchange.publish.assert_not_awaited()

    await adapter.aclose()
    second.close.assert_awaited_once()
