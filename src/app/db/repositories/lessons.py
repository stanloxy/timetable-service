from collections.abc import Iterable, Sequence
from datetime import datetime
from hashlib import blake2b
from uuid import UUID

from sqlalchemy import BigInteger, Select, func, literal, or_, select, text, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.lesson_filters import LessonFilters
from app.db.models import Lesson
from app.enums.lessons import ACTIVE_LESSON_STATUSES, LessonStatus


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

    async def get_for_update(self, lesson_id: UUID) -> Lesson | None:
        query = select(Lesson).where(Lesson.id == lesson_id).with_for_update()
        return (await self._session.scalars(query)).one_or_none()

    async def list_page(
        self, filters: LessonFilters, *, limit: int, offset: int
    ) -> tuple[list[Lesson], int]:
        query = select(Lesson)
        if filters.group_id is not None:
            query = query.where(Lesson.group_id == filters.group_id)
        if filters.instructor_id is not None:
            query = query.where(Lesson.instructor_id == filters.instructor_id)
        if filters.classroom_id is not None:
            query = query.where(Lesson.classroom_id == filters.classroom_id)
        if filters.status is not None:
            query = query.where(Lesson.status == filters.status)
        if filters.starts_from is not None:
            query = query.where(Lesson.starts_at >= filters.starts_from)
        if filters.starts_before is not None:
            query = query.where(Lesson.starts_at < filters.starts_before)

        filtered = query.cte("filtered_lessons")
        total = select(func.count().label("total")).select_from(filtered).subquery()
        # Смещение за пределами BIGINT тоже означает пустую страницу.
        page = (
            select(filtered)
            .order_by(filtered.c.starts_at, filtered.c.id)
            .limit(limit)
            .offset(literal(min(offset, 2**63 - 1), BigInteger))
            .subquery()
        )
        lesson = aliased(Lesson, page)
        statement = (
            select(lesson, total.c.total)
            .select_from(total)
            .outerjoin(page, true())
            .order_by(lesson.starts_at, lesson.id)
        )
        rows = (await self._session.execute(statement)).tuples().all()
        return [item for item, _ in rows if item is not None], int(rows[0][1])

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

    async def start_due_lessons(self, now: datetime) -> int:
        due = (
            select(Lesson.id)
            .where(Lesson.status == LessonStatus.CONFIRMED, Lesson.starts_at <= now)
            .order_by(Lesson.id)
            .with_for_update()
            .cte("due_lessons")
        )
        started = (
            update(Lesson)
            .where(Lesson.id == due.c.id)
            .values(status=LessonStatus.IN_PROGRESS, updated_at=now)
            .returning(Lesson.id)
            .cte("started_lessons")
        )
        result = await self._session.execute(select(func.count()).select_from(started))
        return result.scalar_one()

    def add(self, lesson: Lesson) -> None:
        self._session.add(lesson)
