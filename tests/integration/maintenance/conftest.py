"""Пустое состояние внутри откатываемой транзакции."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.context import AppContext
from app.db.models import Group, Lesson
from app.db.session import session_scope
from app.main import build_context, create_app
from app.maintenance.seed import load_seed, read_all
from app.settings import Settings


@pytest.fixture
async def maintenance_session(db_session: AsyncSession) -> AsyncSession:
    await db_session.execute(delete(Lesson))
    await db_session.execute(delete(Group))
    return db_session


@pytest.fixture
async def seeded_factory(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> async_sessionmaker[AsyncSession]:
    async with session_scope(db_session_factory) as session:
        await session.execute(delete(Lesson))
        await session.execute(delete(Group))
        await load_seed(session, read_all())

    return db_session_factory


@pytest.fixture
async def reset_client(
    seeded_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, AppContext]]:
    context = build_context(Settings(test_mode=True))
    context.session_factory = seeded_factory

    app = create_app()
    app.state.context = context

    transport = httpx.ASGITransport(
        app=app,
        raise_app_exceptions=False,
    )
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            yield client, context
    finally:
        await context.engine.dispose()
