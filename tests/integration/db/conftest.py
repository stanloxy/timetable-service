from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson
from app.enums.lessons import LessonFormat, LessonStatus


@pytest.fixture
async def lesson(db_session: AsyncSession) -> Lesson:
    """Корректное занятие, пока не добавленное в сессию."""
    group_id = UUID("9a000000-0000-4000-8000-000000000099")
    db_session.add(Group(id=group_id, name="Тестовая группа", size=12))
    await db_session.flush()

    starts_at = datetime(2026, 12, 1, 5, tzinfo=UTC)
    return Lesson(
        id=UUID("3d000000-0000-4000-8000-000000000099"),
        group_id=group_id,
        instructor_id=UUID("1b000000-0000-4000-8000-000000000001"),
        classroom_id=None,
        status=LessonStatus.PLANNED,
        format=LessonFormat.ONLINE,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        rescheduled_from_id=None,
        cancel_reason=None,
        created_at=starts_at,
        updated_at=starts_at,
    )
