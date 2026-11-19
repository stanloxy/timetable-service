"""Точка входа приложения: сборка FastAPI, lifespan, подключение роутеров."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from httpx import AsyncClient

from app.api import groups, health, lessons, testing
from app.broker import UnconfiguredBrokerProbe
from app.clients.people import PeopleClient
from app.clock import AdjustableClock
from app.context import AppContext
from app.db.session import make_engine, make_session_factory, session_scope
from app.errors import install_error_handlers
from app.jobs import JobRegistry, run_periodically
from app.maintenance.reset import restore_seed
from app.maintenance.seed import read_all
from app.settings import Settings, get_settings

log = logging.getLogger(__name__)


def build_context(settings: Settings, people_client: PeopleClient) -> AppContext:
    """Создать зависимости процесса (вне lifespan, чтобы тесты собирали контекст без сети)."""
    engine = make_engine(settings.database_url)
    context = AppContext(
        settings=settings,
        engine=engine,
        session_factory=make_session_factory(engine),
        clock=AdjustableClock(),
        # ---> точка расширения: реальная проверка брокера (вместе с издателем событий).
        broker_probe=UnconfiguredBrokerProbe(),
        people_client=people_client,
        jobs=JobRegistry(),
    )

    # ---> точка расширения: регистрация фоновых задач, например
    # context.jobs.register("<job-name>", <корутина, возвращающая int>)
    async def reset_state() -> None:
        data = read_all()
        async with session_scope(context.session_factory) as session:
            await restore_seed(session, data)

    context.reset_state = reset_state
    return context


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл процесса: ресурсы создаются при старте и закрываются при остановке."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    async with AsyncClient(base_url=settings.stub_base_url) as http:
        people_client = PeopleClient(http, settings.stub_timeout_ms)
        context = build_context(settings, people_client)
        app.state.context = context

        stop = asyncio.Event()
        periodic: asyncio.Task[None] | None = None
        try:
            if settings.test_mode:
                log.info("TEST_MODE=1: /__test/* включены, периодические задачи отключены")
            else:
                periodic = asyncio.create_task(
                    run_periodically(context.jobs, settings.jobs_interval_seconds, stop),
                    name="periodic-jobs",
                )
            try:
                yield
            finally:
                stop.set()
                if periodic is not None:
                    await periodic
        finally:
            await context.engine.dispose()


def create_app() -> FastAPI:
    """Собрать приложение."""
    app = FastAPI(
        title="WA service",
        version="0.1.0",
        lifespan=lifespan,
        # Нормативный контракт — openapi.yaml в корне репозитория; автогенерируемая схема
        # остаётся для удобства разработки.
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(testing.router)
    app.include_router(groups.router)
    app.include_router(lessons.router)
    # ---> точка расширения: app.include_router(<предметный роутер>)
    return app


app = create_app()
