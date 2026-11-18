from uuid import UUID

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson
from tests.integration.db.helpers import make_successor


@pytest.mark.parametrize(
    ("field", "constraint"),
    [
        ("group_id", "fk_lessons_group_id"),
        ("rescheduled_from_id", "fk_lessons_rescheduled_from_id"),
    ],
)
async def test_reject_missing_reference(
    db_session: AsyncSession,
    lesson: Lesson,
    field: str,
    constraint: str,
) -> None:
    missing_id = UUID("00000000-0000-4000-8000-000000000001")
    setattr(lesson, field, missing_id)
    db_session.add(lesson)

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert constraint in str(error.value.orig)


async def test_reject_deleting_referenced_group(
    db_session: AsyncSession,
    lesson: Lesson,
) -> None:
    db_session.add(lesson)
    await db_session.flush()

    with pytest.raises(IntegrityError) as error:
        async with db_session.begin_nested():
            await db_session.execute(delete(Group).where(Group.id == lesson.group_id))

    assert "fk_lessons_group_id" in str(error.value.orig)
    assert await db_session.get(Group, lesson.group_id) is not None
    assert await db_session.get(Lesson, lesson.id) is not None


async def test_reject_deleting_predecessor(
    db_session: AsyncSession,
    lesson: Lesson,
) -> None:
    db_session.add(lesson)
    await db_session.flush()

    successor = make_successor(lesson, UUID("3d000000-0000-4000-8000-000000000098"))
    db_session.add(successor)
    await db_session.flush()

    with pytest.raises(IntegrityError) as error:
        async with db_session.begin_nested():
            await db_session.execute(
                delete(Lesson)
                .where(Lesson.id == lesson.id)
                .execution_options(synchronize_session=False)
            )

    assert "fk_lessons_rescheduled_from_id" in str(error.value.orig)
    assert await db_session.get(Lesson, lesson.id) is not None

    db_session.expire(successor)
    await db_session.refresh(successor)
    assert successor.rescheduled_from_id == lesson.id
