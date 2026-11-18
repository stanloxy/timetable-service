"""Сохранение группы, ограничение размера и изоляция тестов."""

from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group

GROUP_ID = UUID("9a000000-0000-4000-8000-000000000099")


@pytest.mark.parametrize("iteration", [1, 2])
async def test_group_commit_is_isolated(
    db_session: AsyncSession,
    iteration: int,
) -> None:
    # Одинаковый UUID в обоих запусках проверяет очистку после теста.
    assert await db_session.get(Group, GROUP_ID) is None

    group = Group(id=GROUP_ID, name=f"Проверка {iteration}", size=1)
    db_session.add(group)
    await db_session.commit()
    db_session.expunge_all()

    saved = await db_session.get(Group, GROUP_ID)
    assert saved is not None
    assert saved.name == f"Проверка {iteration}"
    assert saved.size == 1


@pytest.mark.parametrize("size", [0, -1])
async def test_reject_non_positive_group_size(
    db_session: AsyncSession,
    size: int,
) -> None:
    db_session.add(Group(id=GROUP_ID, name="Проверка", size=size))

    with pytest.raises(IntegrityError):
        await db_session.flush()
