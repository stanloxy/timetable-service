"""Загрузка seed и восстановление исходных данных."""

from copy import deepcopy
from uuid import UUID

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson
from app.maintenance.reset import restore_seed
from app.maintenance.seed import load_seed, read_all
from tests.integration.maintenance.helpers import snapshot

G1 = UUID("9a000000-0000-4000-8000-000000000001")
G3 = UUID("9a000000-0000-4000-8000-000000000003")
EXTRA_GROUP = UUID("9a000000-0000-4000-8000-000000000099")


async def test_load_exact_seed(
    maintenance_session: AsyncSession,
) -> None:
    data = read_all()
    original_input = deepcopy(data)

    await load_seed(maintenance_session, data)

    assert await snapshot(maintenance_session) == original_input
    assert data == original_input


@pytest.mark.parametrize("repetitions", [2, 3])
async def test_seed_is_idempotent(
    maintenance_session: AsyncSession,
    repetitions: int,
) -> None:
    data = read_all()

    for _ in range(repetitions):
        await load_seed(maintenance_session, data)

    assert await snapshot(maintenance_session) == data


async def test_restore_missing_records(
    maintenance_session: AsyncSession,
) -> None:
    data = read_all()
    await load_seed(maintenance_session, data)

    await maintenance_session.execute(delete(Lesson).where(Lesson.group_id == G3))
    await maintenance_session.execute(delete(Group).where(Group.id == G3))

    await load_seed(maintenance_session, data)

    assert await snapshot(maintenance_session) == data


async def test_seed_preserves_changes(
    maintenance_session: AsyncSession,
) -> None:
    data = read_all()
    await load_seed(maintenance_session, data)

    await maintenance_session.execute(update(Group).where(Group.id == G1).values(name="Изменено"))
    maintenance_session.add(Group(id=EXTRA_GROUP, name="Дополнительная", size=5))
    await maintenance_session.flush()
    before = await snapshot(maintenance_session)

    await load_seed(maintenance_session, data)

    assert await snapshot(maintenance_session) == before


async def test_seed_preserves_extra_lesson_and_reset_removes_it(
    maintenance_session: AsyncSession,
) -> None:
    data = read_all()
    await load_seed(maintenance_session, data)

    # Дополнительное корректное занятие с другим UUID.
    extra = deepcopy(data["lessons"][0])
    extra["id"] = "3d000000-0000-4000-8000-000000000099"

    await load_seed(
        maintenance_session,
        {"groups": [], "lessons": [extra]},
    )
    before = await snapshot(maintenance_session)
    assert len(before["lessons"]) == 9

    await load_seed(maintenance_session, data)
    assert await snapshot(maintenance_session) == before

    await restore_seed(maintenance_session, data)
    assert await snapshot(maintenance_session) == data


async def test_reset_restores_exact_seed(
    maintenance_session: AsyncSession,
) -> None:
    data = read_all()
    await load_seed(maintenance_session, data)

    await maintenance_session.execute(
        update(Group).where(Group.id == G1).values(name="RESET_CHECK")
    )
    maintenance_session.add(Group(id=EXTRA_GROUP, name="Дополнительная", size=5))
    await maintenance_session.flush()

    await restore_seed(maintenance_session, data)
    assert await snapshot(maintenance_session) == data

    await restore_seed(maintenance_session, data)
    assert await snapshot(maintenance_session) == data
