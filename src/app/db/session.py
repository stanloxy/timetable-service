"""Движок PostgreSQL, сессии, транзакции и проверка соединения."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str) -> AsyncEngine:
    """Создать движок. ``pool_pre_ping`` — чтобы readiness не держал мёртвые соединения."""
    return create_async_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий: одна сессия — одна единица работы (запрос или шаг фоновой задачи)."""
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Сессия с автоматическим commit при успехе и rollback при исключении."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def check_database(engine: AsyncEngine) -> bool:
    """Проверка для readiness: удалось ли выполнить ``SELECT 1``."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        # Любая ошибка соединения или запроса означает «БД недоступна»; детали — в логах драйвера.
        return False
    return True
