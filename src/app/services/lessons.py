from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clock import Clock
from app.db.models import Lesson
from app.db.repositories.groups import GroupRepository
from app.db.repositories.lessons import LessonRepository
from app.db.session import session_scope
from app.enums.lessons import LessonStatus
from app.services.exceptions.lessons import LessonConflictError
from app.services.exceptions.resources import ResourceNotFoundError
from app.services.lesson_reference_data import PeopleReader
from app.services.lesson_results import LessonValidation, LessonWarning
from app.services.lesson_rules import LessonCandidate, check_lesson


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
