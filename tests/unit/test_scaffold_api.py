"""Служебные эндпоинты каркаса без БД и брокера: формат ошибок, тестовый режим, часы, задачи."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest

from app.broker import UnconfiguredBrokerProbe
from app.clients.people import PeopleClient
from app.clock import AdjustableClock
from app.context import AppContext
from app.db.session import make_engine, make_session_factory
from app.jobs import JobRegistry
from app.main import create_app
from app.settings import Settings

FROZEN = "2026-11-30T03:00:00Z"


@asynccontextmanager
async def _api_client(*, test_mode: bool) -> AsyncIterator[tuple[httpx.AsyncClient, AppContext]]:
    """Клиент приложения с контекстом, собранным вручную без lifespan."""
    settings = Settings(
        test_mode=test_mode,
        database_url="postgresql+asyncpg://wa:wa@127.0.0.1:1/unreachable",
    )

    def reject_upstream(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected people-stub request: {request.url}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(reject_upstream), base_url=settings.stub_base_url
    ) as upstream:
        engine = make_engine(settings.database_url)
        try:
            context = AppContext(
                settings=settings,
                engine=engine,
                session_factory=make_session_factory(engine),
                clock=AdjustableClock(),
                broker_probe=UnconfiguredBrokerProbe(),
                people_client=PeopleClient(upstream, settings.stub_timeout_ms),
                jobs=JobRegistry(),
            )
            app = create_app()
            app.state.context = context
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as http:
                yield http, context
        finally:
            await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[tuple[httpx.AsyncClient, AppContext]]:
    async with _api_client(test_mode=True) as api:
        yield api


async def test_live(client: tuple[httpx.AsyncClient, AppContext]) -> None:
    http, _ = client
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
    async with _api_client(test_mode=False) as (http, _):
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


async def test_reset_without_callback_returns_501(
    client: tuple[httpx.AsyncClient, AppContext],
) -> None:
    http, _ = client
    response = await http.post("/__test/reset")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"


async def test_reset_calls_callback(
    client: tuple[httpx.AsyncClient, AppContext],
) -> None:
    http, context = client
    called = False

    async def reset() -> None:
        nonlocal called
        called = True

    context.reset_state = reset

    response = await http.post("/__test/reset")

    assert response.status_code == 204
    assert response.content == b""
    assert called
