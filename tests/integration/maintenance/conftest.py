"""Пустое состояние внутри откатываемой транзакции."""

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson


@pytest.fixture
async def maintenance_session(db_session: AsyncSession) -> AsyncSession:
    await db_session.execute(delete(Lesson))
    await db_session.execute(delete(Group))
    return db_session
