from collections.abc import Iterable, Sequence
from datetime import datetime
from hashlib import blake2b
from uuid import UUID

from sqlalchemy import Select, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lesson
from app.enums.lessons import ACTIVE_LESSON_STATUSES


def _active_overlaps(
    starts_at: datetime, ends_at: datetime, exclude_lesson_id: UUID | None
) -> Select[tuple[Lesson]]:
    query = select(Lesson).where(
        Lesson.status.in_(ACTIVE_LESSON_STATUSES),
        Lesson.starts_at < ends_at,
        Lesson.ends_at > starts_at,
    )
    if exclude_lesson_id is not None:
        query = query.where(Lesson.id != exclude_lesson_id)
    return query


def _resource_key(kind: str, resource_id: UUID) -> int:
    digest = blake2b(kind.encode() + resource_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


class LessonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, lesson_id: UUID) -> Lesson | None:
        return await self._session.get(Lesson, lesson_id)

    async def lock_resources(self, resources: Iterable[tuple[str, UUID]]) -> None:
        keys = {_resource_key(kind, resource_id) for kind, resource_id in resources}
        for key in sorted(keys):
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(CAST(:key AS BIGINT))"), {"key": key}
            )

    async def find_conflicting(
        self,
        *,
        starts_at: datetime,
        ends_at: datetime,
        instructor_id: UUID,
        classroom_id: UUID | None,
        group_id: UUID,
        exclude_lesson_id: UUID | None,
    ) -> Sequence[Lesson]:
        resources = [Lesson.instructor_id == instructor_id, Lesson.group_id == group_id]
        if classroom_id is not None:
            resources.append(Lesson.classroom_id == classroom_id)
        query = (
            _active_overlaps(starts_at, ends_at, exclude_lesson_id)
            .where(or_(*resources))
            .order_by(Lesson.starts_at, Lesson.id)
        )
        return (await self._session.scalars(query)).all()

    async def find_instructor_lessons(
        self,
        instructor_id: UUID,
        starts_at: datetime,
        ends_at: datetime,
        exclude_lesson_id: UUID | None,
    ) -> Sequence[Lesson]:
        query = _active_overlaps(starts_at, ends_at, exclude_lesson_id).where(
            Lesson.instructor_id == instructor_id
        )
        return (await self._session.scalars(query)).all()

    def add(self, lesson: Lesson) -> None:
        self._session.add(lesson)
