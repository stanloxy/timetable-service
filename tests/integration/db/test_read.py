from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.groups import GroupRepository
from app.db.repositories.lessons import LessonRepository
from app.services.exceptions import ResourceKind, ResourceNotFoundError
from app.services.groups import GroupService
from app.services.lessons import LessonService


@pytest.mark.parametrize("resource", ["group", "lesson"])
@pytest.mark.parametrize("exists", [True, False])
async def test_repository_read(
    seeded_factory: async_sessionmaker[AsyncSession],
    resource: ResourceKind,
    exists: bool,
) -> None:
    prefix = "9a" if resource == "group" else "3d"
    suffix = "01" if exists else "99"
    resource_id = UUID(f"{prefix}000000-0000-4000-8000-0000000000{suffix}")

    async with seeded_factory() as session:
        result = await (
            GroupRepository(session).get_by_id(resource_id)
            if resource == "group"
            else LessonRepository(session).get_by_id(resource_id)
        )

    if exists:
        assert result is not None
        assert result.id == resource_id
    else:
        assert result is None


@pytest.mark.parametrize("resource", ["group", "lesson"])
@pytest.mark.parametrize("exists", [True, False])
async def test_service_read(
    seeded_factory: async_sessionmaker[AsyncSession],
    resource: ResourceKind,
    exists: bool,
) -> None:
    prefix = "9a" if resource == "group" else "3d"
    suffix = "01" if exists else "99"
    resource_id = UUID(f"{prefix}000000-0000-4000-8000-0000000000{suffix}")

    operation = (
        GroupService(seeded_factory).get_by_id(resource_id)
        if resource == "group"
        else LessonService(seeded_factory).get_by_id(resource_id)
    )

    if exists:
        result = await operation
        assert result.id == resource_id
    else:
        with pytest.raises(ResourceNotFoundError) as error:
            await operation

        assert error.value.resource == resource
        assert error.value.resource_id == resource_id
