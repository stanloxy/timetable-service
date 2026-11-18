from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Lesson


class LessonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, lesson_id: UUID) -> Lesson | None:
        return await self._session.get(Lesson, lesson_id)
