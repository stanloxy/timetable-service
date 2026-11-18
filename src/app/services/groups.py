from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Group
from app.db.repositories.groups import GroupRepository
from app.db.session import session_scope
from app.services.exceptions import ResourceNotFoundError


class GroupService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self.group_repo: type[GroupRepository] = GroupRepository

    async def get_by_id(self, group_id: UUID) -> Group:
        async with session_scope(self._session_factory) as session:
            group = await self.group_repo(session).get_by_id(group_id)

            if group is None:
                raise ResourceNotFoundError("group", group_id)

            return group
