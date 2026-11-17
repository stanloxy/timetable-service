"""Контекст приложения: всё, что создаётся в lifespan и нужно обработчикам и задачам."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.broker import BrokerProbe
from app.clock import AdjustableClock
from app.jobs import JobRegistry
from app.settings import Settings


@dataclass
class AppContext:
    """Зависимости процесса. Хранится в ``app.state.context``; доступ через ``get_context``."""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    clock: AdjustableClock
    broker_probe: BrokerProbe
    jobs: JobRegistry = field(default_factory=JobRegistry)
    # POST /__test/reset: callback очистки и восстановления seed подключается в build_context.
    reset_state: Callable[[], Awaitable[None]] | None = None


def get_context(request: Request) -> AppContext:
    """Типизированный доступ к контексту из обработчика FastAPI."""
    context = request.app.state.context
    if not isinstance(context, AppContext):
        msg = "Контекст приложения не инициализирован: lifespan не отработал"
        raise RuntimeError(msg)
    return context
