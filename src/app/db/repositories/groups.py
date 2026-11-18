from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group


class GroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, group_id: UUID) -> Group | None:
        return await self._session.get(Group, group_id)
