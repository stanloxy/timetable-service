import asyncio

import httpx
import pytest

from app.clock import Clock
from app.main import create_app
from app.services.lessons import LessonService
from app.settings import get_settings

_PATH = "/__test/jobs/lesson-status-sweeper/run"


@pytest.mark.parametrize("test_mode", [False, True])
async def test_registered_sweeper_uses_the_configured_execution_mode(
    monkeypatch: pytest.MonkeyPatch, test_mode: bool
) -> None:
    calls: list[Clock] = []
    ran_twice = asyncio.Event()

    async def sweep(_service: LessonService, *, clock: Clock) -> int:
        calls.append(clock)
        if len(calls) == 2:
            ran_twice.set()
        return 3

    monkeypatch.setattr(LessonService, "start_due_lessons", sweep)
    monkeypatch.setenv("TEST_MODE", "1" if test_mode else "0")
    monkeypatch.setenv("JOBS_INTERVAL_SECONDS", "1")
    get_settings.cache_clear()
    app = create_app()
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as http,
        ):
            if test_mode:
                await asyncio.sleep(0)
                assert calls == []
                response = await http.post(_PATH)
                assert response.status_code == 200, response.text
                assert response.json() == {"processed": 3}
                assert calls == [app.state.context.clock]
                unknown = await http.post("/__test/jobs/unknown/run")
                assert unknown.status_code == 404
                assert unknown.json()["error"]["code"] == "NOT_FOUND"
            else:
                response = await http.post(_PATH)
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "NOT_FOUND"
                await asyncio.wait_for(ran_twice.wait(), timeout=5)
                assert calls == [app.state.context.clock] * 2
    finally:
        get_settings.cache_clear()
