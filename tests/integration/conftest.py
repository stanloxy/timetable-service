"""Фикстуры настоящей PostgreSQL; схема заранее создаётся миграциями."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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
