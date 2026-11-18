from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Lesson
from app.db.repositories.lessons import LessonRepository
from app.db.session import session_scope
from app.services.exceptions import ResourceNotFoundError


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
