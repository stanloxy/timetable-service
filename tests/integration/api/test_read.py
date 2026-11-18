import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.context import AppContext
from app.maintenance.seed import read_all
from tests.e2e.contract import ContractChecker
from tests.integration.maintenance.helpers import snapshot


@pytest.mark.parametrize(
    ("collection", "schema"),
    [("groups", "Group"), ("lessons", "Lesson")],
)
async def test_read_all_seed_records(
    api_client: tuple[httpx.AsyncClient, AppContext],
    seeded_factory: async_sessionmaker[AsyncSession],
    contract: ContractChecker,
    collection: str,
    schema: str,
) -> None:
    client, context = api_client

    # Чтение доступно вне тестового режима и без people-stub.
    context.settings.test_mode = False
    context.settings.stub_base_url = "http://127.0.0.1:1"

    async with seeded_factory() as session:
        before = await snapshot(session)

    for expected in read_all()[collection]:
        response = await client.get(f"/{collection}/{expected['id']}")

        assert response.status_code == 200
        contract.assert_schema(response.json(), schema)
        assert response.json() == expected

    async with seeded_factory() as session:
        assert await snapshot(session) == before


@pytest.mark.parametrize(
    ("collection", "resource_id", "detail_key"),
    [
        ("groups", "9a000000-0000-4000-8000-000000000099", "group_id"),
        ("lessons", "3d000000-0000-4000-8000-000000000099", "lesson_id"),
    ],
)
async def test_read_missing_resource(
    api_client: tuple[httpx.AsyncClient, AppContext],
    contract: ContractChecker,
    collection: str,
    resource_id: str,
    detail_key: str,
) -> None:
    client, _ = api_client
    response = await client.get(f"/{collection}/{resource_id}")

    details = contract.assert_error(response, 404, "NOT_FOUND")
    assert details == {detail_key: resource_id}
