"""HTTP reset, сохранение часов и атомарность операций."""

from uuid import UUID

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.context import AppContext
from app.db.models import Group
from app.db.session import session_scope
from app.maintenance.seed import load_seed, read_all
from tests.integration.maintenance.helpers import snapshot

FROZEN = "2026-11-30T03:00:00Z"
G1 = UUID("9a000000-0000-4000-8000-000000000001")


@pytest.mark.parametrize("frozen", [True, False])
async def test_reset_preserves_clock(
    api_client: tuple[httpx.AsyncClient, AppContext],
    seeded_factory: async_sessionmaker[AsyncSession],
    frozen: bool,
) -> None:
    client, context = api_client

    if frozen:
        response = await client.put("/__test/time", json={"now": FROZEN})
        assert response.status_code == 200

    async with session_scope(seeded_factory) as session:
        await session.execute(update(Group).where(Group.id == G1).values(name="RESET_CHECK"))

    for _ in range(2):
        response = await client.post("/__test/reset")

        assert response.status_code == 204
        assert response.content == b""
        assert context.clock.is_frozen == frozen

        if frozen:
            time_response = await client.get("/__test/time")
            assert time_response.json() == {"now": FROZEN}

        async with seeded_factory() as session:
            assert await snapshot(session) == read_all()


async def test_reset_hidden_outside_test_mode(
    api_client: tuple[httpx.AsyncClient, AppContext],
    seeded_factory: async_sessionmaker[AsyncSession],
) -> None:
    client, context = api_client
    await client.put("/__test/time", json={"now": FROZEN})

    async with session_scope(seeded_factory) as session:
        await session.execute(update(Group).where(Group.id == G1).values(name="Не менять"))
        before = await snapshot(session)

    context.settings.test_mode = False
    response = await client.post("/__test/reset")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert context.clock.is_frozen
    assert context.clock.now().isoformat() == "2026-11-30T03:00:00+00:00"

    async with seeded_factory() as session:
        assert await snapshot(session) == before


async def test_failed_seed_rolls_back(
    seeded_factory: async_sessionmaker[AsyncSession],
) -> None:
    invalid = read_all()
    invalid["groups"].append(
        {
            "id": "9a000000-0000-4000-8000-000000000099",
            "name": "Не должна сохраниться",
            "size": 5,
        }
    )
    invalid["lessons"][-1]["id"] = "3d000000-0000-4000-8000-000000000099"
    invalid["lessons"][-1]["status"] = "UNKNOWN"

    async with seeded_factory() as session:
        before = await snapshot(session)

    with pytest.raises(IntegrityError):
        async with session_scope(seeded_factory) as session:
            await load_seed(session, invalid)

    async with seeded_factory() as session:
        assert await snapshot(session) == before


async def test_failed_reset_rolls_back(
    api_client: tuple[httpx.AsyncClient, AppContext],
    seeded_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, context = api_client
    await client.put("/__test/time", json={"now": FROZEN})

    async with session_scope(seeded_factory) as session:
        await session.execute(update(Group).where(Group.id == G1).values(name="До ошибки"))
        before = await snapshot(session)

    invalid = read_all()
    invalid["lessons"][-1]["status"] = "UNKNOWN"
    monkeypatch.setattr("app.main.read_all", lambda: invalid)

    response = await client.post("/__test/reset")

    assert response.status_code == 500
    assert context.clock.is_frozen
    assert context.clock.now().isoformat() == "2026-11-30T03:00:00+00:00"

    async with seeded_factory() as session:
        assert await snapshot(session) == before
