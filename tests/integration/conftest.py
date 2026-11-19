"""Фикстуры настоящей PostgreSQL; схема заранее создаётся миграциями."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.clients.people import PeopleClient
from app.context import AppContext
from app.db.models import Group, Lesson
from app.db.session import session_scope
from app.main import build_context, create_app
from app.maintenance.seed import load_seed, read_all
from app.settings import Settings
from tools.test_db import load_test_database_url


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(load_test_database_url())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session_factory(
    db_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield async_sessionmaker(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
        finally:
            await transaction.rollback()


@pytest.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with db_session_factory() as session:
        yield session


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
async def api_client(
    seeded_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[httpx.AsyncClient, AppContext]]:
    database_url = load_test_database_url().render_as_string(hide_password=False)
    settings = Settings(test_mode=True, database_url=database_url)

    def reject_upstream(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected people-stub request: {request.url}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(reject_upstream), base_url=settings.stub_base_url
    ) as upstream:
        context = build_context(settings, PeopleClient(upstream, settings.stub_timeout_ms))
        context.session_factory = seeded_factory

        app = create_app()
        app.state.context = context
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                yield client, context
        finally:
            await context.engine.dispose()
