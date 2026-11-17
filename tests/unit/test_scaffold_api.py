"""Служебные эндпоинты каркаса без БД и брокера: формат ошибок, тестовый режим, часы, задачи."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from app.broker import UnconfiguredBrokerProbe
from app.clock import AdjustableClock
from app.context import AppContext
from app.db.session import make_engine, make_session_factory
from app.jobs import JobRegistry
from app.main import create_app
from app.settings import Settings

FROZEN = "2026-11-30T03:00:00Z"


def _build_app(*, test_mode: bool) -> tuple[FastAPI, AppContext]:
    """Приложение с контекстом, собранным вручную: lifespan не запускается, сеть не нужна."""
    settings = Settings(
        test_mode=test_mode,
        database_url="postgresql+asyncpg://wa:wa@127.0.0.1:1/unreachable",
    )
    engine = make_engine(settings.database_url)
    context = AppContext(
        settings=settings,
        engine=engine,
        session_factory=make_session_factory(engine),
        clock=AdjustableClock(),
        broker_probe=UnconfiguredBrokerProbe(),
        jobs=JobRegistry(),
    )
    app = create_app()
    app.state.context = context
    return app, context


@pytest.fixture
async def client() -> AsyncIterator[tuple[httpx.AsyncClient, AppContext]]:
    app, context = _build_app(test_mode=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, context


async def test_live() -> None:
    app, _ = _build_app(test_mode=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_is_degraded_without_dependencies(
    client: tuple[httpx.AsyncClient, AppContext],
) -> None:
    http, _ = client
    response = await http.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "fail", "broker": "fail"}


async def test_unknown_route_uses_platform_error_format(
    client: tuple[httpx.AsyncClient, AppContext],
) -> None:
    http, _ = client
    response = await http.get("/no-such-route")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert set(body["error"]) == {"code", "message", "details"}


async def test_test_endpoints_hidden_when_test_mode_off() -> None:
    app, _ = _build_app(test_mode=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.get("/__test/time")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_time_set_get_reset(client: tuple[httpx.AsyncClient, AppContext]) -> None:
    http, context = client

    put = await http.put("/__test/time", json={"now": FROZEN})
    assert put.status_code == 200
    assert put.json() == {"now": FROZEN}
    assert context.clock.now() == datetime(2026, 11, 30, 3, 0, tzinfo=UTC)

    get = await http.get("/__test/time")
    assert get.json() == {"now": FROZEN}

    delete = await http.delete("/__test/time")
    assert delete.status_code == 204
    assert not context.clock.is_frozen


async def test_time_without_offset_is_422(client: tuple[httpx.AsyncClient, AppContext]) -> None:
    http, _ = client
    response = await http.put("/__test/time", json={"now": "2026-11-30T03:00:00"})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "now" in body["details"]["fields"]


async def test_invalid_json_is_400(client: tuple[httpx.AsyncClient, AppContext]) -> None:
    http, _ = client
    response = await http.put(
        "/__test/time", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


async def test_wrong_field_type_is_400(client: tuple[httpx.AsyncClient, AppContext]) -> None:
    http, _ = client
    # Число pydantic трактует как unix-время, поэтому «не тот тип» здесь — объект вместо строки.
    response = await http.put("/__test/time", json={"now": {"year": 2026}})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


async def test_jobs_run_registered_and_unknown(
    client: tuple[httpx.AsyncClient, AppContext],
) -> None:
    http, context = client
    calls: list[str] = []

    async def sweep() -> int:
        calls.append("run")
        return 3

    context.jobs.register("demo-job", sweep)

    ok = await http.post("/__test/jobs/demo-job/run")
    assert ok.status_code == 200
    assert ok.json() == {"processed": 3}
    assert calls == ["run"]

    missing = await http.post("/__test/jobs/unknown-job/run")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


async def test_reset_not_implemented_in_scaffold(
    client: tuple[httpx.AsyncClient, AppContext],
) -> None:
    http, _ = client
    response = await http.post("/__test/reset")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"
