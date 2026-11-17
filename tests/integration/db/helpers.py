from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lesson
from app.enums.lessons import LessonStatus


def make_successor(original: Lesson, successor_id: UUID) -> Lesson:
    """Подготовить новое занятие со ссылкой на исходное."""
    return Lesson(
        id=successor_id,
        group_id=original.group_id,
        instructor_id=original.instructor_id,
        classroom_id=original.classroom_id,
        status=LessonStatus.PLANNED,
        format=original.format,
        starts_at=original.starts_at + timedelta(days=1),
        ends_at=original.ends_at + timedelta(days=1),
        rescheduled_from_id=original.id,
        cancel_reason=None,
        created_at=original.created_at,
        updated_at=original.updated_at,
    )


async def save_in_savepoint(
    session: AsyncSession,
    lesson: Lesson,
) -> None:
    async with session.begin_nested():
        session.add(lesson)
        await session.flush()
