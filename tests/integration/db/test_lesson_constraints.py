from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lesson
from app.enums.lessons import LessonFormat, LessonStatus


@pytest.mark.parametrize("minutes", [30, 480])
async def test_accept_duration_boundaries(
    db_session: AsyncSession,
    lesson: Lesson,
    minutes: int,
) -> None:
    lesson.ends_at = lesson.starts_at + timedelta(minutes=minutes)
    db_session.add(lesson)
    await db_session.flush()


@pytest.mark.parametrize("minutes", [-1, 0, 29, 481])
async def test_reject_invalid_duration(
    db_session: AsyncSession,
    lesson: Lesson,
    minutes: int,
) -> None:
    lesson.ends_at = lesson.starts_at + timedelta(minutes=minutes)
    db_session.add(lesson)

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert "ck_lessons_duration" in str(error.value.orig)


@pytest.mark.parametrize(
    ("lesson_format", "has_classroom", "allowed"),
    [
        ("ONLINE", False, True),
        ("ONLINE", True, False),
        ("IN_PERSON", True, True),
        ("IN_PERSON", False, False),
    ],
)
async def test_format_classroom_consistency(
    db_session: AsyncSession,
    lesson: Lesson,
    lesson_format: str,
    has_classroom: bool,
    allowed: bool,
) -> None:
    lesson.format = LessonFormat(lesson_format)
    lesson.classroom_id = UUID("2c000000-0000-4000-8000-000000000001") if has_classroom else None
    db_session.add(lesson)

    if allowed:
        await db_session.flush()
    else:
        with pytest.raises(IntegrityError) as error:
            await db_session.flush()

        assert "ck_lessons_format_classroom" in str(error.value.orig)


@pytest.mark.parametrize(
    "status",
    [
        "PLANNED",
        "CONFIRMED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
        "RESCHEDULED",
    ],
)
async def test_accept_allowed_status(
    db_session: AsyncSession,
    lesson: Lesson,
    status: str,
) -> None:
    lesson.status = LessonStatus(status)
    db_session.add(lesson)
    await db_session.flush()


@pytest.mark.parametrize(
    ("field", "constraint"),
    [
        ("status", "ck_lessons_status"),
        ("format", "ck_lessons_format"),
    ],
)
async def test_reject_unknown_enum_value(
    db_session: AsyncSession,
    lesson: Lesson,
    field: str,
    constraint: str,
) -> None:
    setattr(lesson, field, "UNKNOWN")
    db_session.add(lesson)

    with pytest.raises(IntegrityError) as error:
        await db_session.flush()

    assert constraint in str(error.value.orig)


async def test_read_returns_python_enums(
    db_session: AsyncSession,
    lesson: Lesson,
) -> None:
    lesson_id = lesson.id
    db_session.add(lesson)
    await db_session.flush()
    db_session.expunge_all()

    saved = await db_session.get(Lesson, lesson_id)

    assert saved is not None
    assert saved.status is LessonStatus.PLANNED
    assert saved.format is LessonFormat.ONLINE
