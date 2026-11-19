from dataclasses import replace
from datetime import datetime
from typing import TypedDict
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import Clock
from app.db.models import Lesson
from app.db.repositories.groups import GroupRepository
from app.db.repositories.lessons import LessonFilters, LessonRepository
from app.db.session import session_scope
from app.enums.lessons import LessonFormat, LessonStatus
from app.services.exceptions.lessons import LessonConflictError, LessonNotEditableError
from app.services.exceptions.resources import ResourceNotFoundError
from app.services.lesson_reference_data import PeopleReader
from app.services.lesson_results import LessonValidation, LessonWarning
from app.services.lesson_rules import LessonCandidate, check_lesson


class LessonChanges(TypedDict, total=False):
    instructor_id: UUID
    classroom_id: UUID | None
    format: LessonFormat
    starts_at: datetime
    ends_at: datetime


class LessonService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self.lesson_repo: type[LessonRepository] = LessonRepository

    async def get_by_id(self, lesson_id: UUID) -> Lesson:
        async with session_scope(self._session_factory) as session:
            lesson = await self.lesson_repo(session).get_by_id(lesson_id)

            if lesson is None:
                raise ResourceNotFoundError("lesson", lesson_id)

            return lesson

    async def list_page(
        self, filters: LessonFilters, *, limit: int, offset: int
    ) -> tuple[list[Lesson], int]:
        async with session_scope(self._session_factory) as session:
            return await self.lesson_repo(session).list_page(filters, limit=limit, offset=offset)

    async def edit(
        self, lesson_id: UUID, changes: LessonChanges, *, people: PeopleReader, clock: Clock
    ) -> tuple[Lesson, list[LessonWarning]]:
        async with session_scope(self._session_factory) as session:
            lessons = self.lesson_repo(session)
            lesson = await lessons.get_for_update(lesson_id)
            if lesson is None:
                raise ResourceNotFoundError("lesson", lesson_id)
            if lesson.status is not LessonStatus.PLANNED:
                raise LessonNotEditableError(lesson.status)

            original = LessonCandidate(
                group_id=lesson.group_id,
                instructor_id=lesson.instructor_id,
                classroom_id=lesson.classroom_id,
                format=lesson.format,
                starts_at=lesson.starts_at,
                ends_at=lesson.ends_at,
            )
            # В changes есть только переданные поля, включая явный classroom_id=None.
            candidate = replace(original, **changes)
            warnings = await check_lesson(
                candidate,
                groups=GroupRepository(session),
                lessons=lessons,
                people=people,
                lock_for_write=True,
                exclude_lesson_id=lesson_id,
                previous_resources=original.resources().items(),
            )
            lesson.instructor_id = candidate.instructor_id
            lesson.classroom_id = candidate.classroom_id
            lesson.format = candidate.format
            lesson.starts_at = candidate.starts_at
            lesson.ends_at = candidate.ends_at
            lesson.updated_at = clock.now()
        return lesson, warnings

    async def create(
        self, candidate: LessonCandidate, *, people: PeopleReader, clock: Clock
    ) -> tuple[Lesson, list[LessonWarning]]:
        async with session_scope(self._session_factory) as session:
            lessons = self.lesson_repo(session)
            warnings = await check_lesson(
                candidate,
                groups=GroupRepository(session),
                lessons=lessons,
                people=people,
                lock_for_write=True,
            )
            now = clock.now()
            lesson = Lesson(
                id=uuid4(),
                group_id=candidate.group_id,
                instructor_id=candidate.instructor_id,
                classroom_id=candidate.classroom_id,
                format=candidate.format,
                starts_at=candidate.starts_at,
                ends_at=candidate.ends_at,
                status=LessonStatus.PLANNED,
                rescheduled_from_id=None,
                cancel_reason=None,
                created_at=now,
                updated_at=now,
            )
            lessons.add(lesson)
        return lesson, warnings

    async def validate(
        self, candidate: LessonCandidate, *, people: PeopleReader
    ) -> LessonValidation:
        try:
            async with session_scope(self._session_factory) as session:
                warnings = await check_lesson(
                    candidate,
                    groups=GroupRepository(session),
                    lessons=self.lesson_repo(session),
                    people=people,
                    lock_for_write=False,
                )
        except LessonConflictError as exc:
            return LessonValidation(warnings=[], violation=exc.violation)
        return LessonValidation(warnings=warnings)
