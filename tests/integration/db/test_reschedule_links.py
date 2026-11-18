from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lesson
from tests.integration.db.helpers import make_successor, save_in_savepoint


async def test_reject_second_successor(
    db_session: AsyncSession,
    lesson: Lesson,
) -> None:
    db_session.add(lesson)
    await db_session.flush()

    first = make_successor(lesson, UUID("3d000000-0000-4000-8000-000000000097"))
    db_session.add(first)
    await db_session.flush()

    second = make_successor(lesson, UUID("3d000000-0000-4000-8000-000000000098"))

    # Ошибка откатит только попытку создания второго преемника.
    with pytest.raises(IntegrityError) as error:
        await save_in_savepoint(db_session, second)

    assert "uq_lessons_rescheduled_from_id" in str(error.value.orig)

    successor_ids = await db_session.scalars(
        select(Lesson.id).where(Lesson.rescheduled_from_id == lesson.id)
    )
    assert list(successor_ids) == [first.id]


async def test_allow_multiple_lessons_without_predecessors(
    db_session: AsyncSession,
    lesson: Lesson,
) -> None:
    another = make_successor(lesson, UUID("3d000000-0000-4000-8000-000000000098"))
    another.rescheduled_from_id = None

    db_session.add_all([lesson, another])
    await db_session.flush()


async def test_reject_self_reschedule(
    db_session: AsyncSession,
    lesson: Lesson,
) -> None:
    lesson.rescheduled_from_id = lesson.id
    db_session.add(lesson)

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert "ck_lessons_no_self_reschedule" in str(error.value.orig)
