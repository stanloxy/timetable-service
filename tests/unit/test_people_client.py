import asyncio
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app import main
from app.clients.people import PeopleClient
from app.enums.lessons import LessonFormat
from app.errors import install_error_handlers
from app.main import create_app, lifespan
from app.services.lesson_reference_data import collect_lesson_reference_data
from app.settings import get_settings

INSTRUCTOR_ID = UUID("1b000000-0000-4000-8000-000000000001")
CLASSROOM_ID = UUID("2c000000-0000-4000-8000-000000000001")
PROFILE_PATH = f"/instructors/{INSTRUCTOR_ID}"
AVAILABILITY_PATH = f"{PROFILE_PATH}/availability"
CLASSROOM_PATH = f"/classrooms/{CLASSROOM_ID}"
RESPONSES: dict[str, dict[str, object]] = {
    PROFILE_PATH: {
        "id": str(INSTRUCTOR_ID),
        "full_name": "Анна Королёва",
        "max_hours_per_day": 6.5,
        "timezone": "Asia/Yekaterinburg",
    },
    AVAILABILITY_PATH: {
        "instructor_id": str(INSTRUCTOR_ID),
        "timezone": "Asia/Yekaterinburg",
        "windows": [{"weekday": 1, "from": "09:00", "to": "18:00"}],
    },
    CLASSROOM_PATH: {
        "id": str(CLASSROOM_ID),
        "name": "Ауд. 101",
        "capacity": 30,
        "online_capable": True,
    },
}


async def test_people_client_reads_typed_responses() -> None:
    paths: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "people.example"
        paths.append(request.url.path)
        return httpx.Response(200, json=RESPONSES[request.url.path])

    async with httpx.AsyncClient(
        base_url="http://people.example", transport=httpx.MockTransport(transport)
    ) as http:
        client = PeopleClient(http, timeout_ms=2000)
        instructor = await client.get_instructor(INSTRUCTOR_ID)
        availability = await client.get_availability(INSTRUCTOR_ID)
        classroom = await client.get_classroom(CLASSROOM_ID)

    assert paths == [PROFILE_PATH, AVAILABILITY_PATH, CLASSROOM_PATH]
    assert instructor is not None
    assert instructor.id == INSTRUCTOR_ID
    assert instructor.max_hours_per_day == 6.5
    assert availability is not None
    assert availability.instructor_id == INSTRUCTOR_ID
    assert availability.timezone == instructor.timezone
    assert [window.model_dump() for window in availability.windows] == [
        {"weekday": 1, "starts_at": "09:00", "ends_at": "18:00"}
    ]
    assert classroom is not None
    assert classroom.id == CLASSROOM_ID
    assert classroom.capacity == 30


@pytest.mark.parametrize(
    ("failed_path", "failure", "status", "code", "details"),
    [
        (PROFILE_PATH, 404, 422, "INSTRUCTOR_NOT_FOUND", {"instructor_id": str(INSTRUCTOR_ID)}),
        (
            AVAILABILITY_PATH,
            404,
            422,
            "INSTRUCTOR_NOT_FOUND",
            {"instructor_id": str(INSTRUCTOR_ID)},
        ),
        (CLASSROOM_PATH, 404, 422, "CLASSROOM_NOT_FOUND", {"classroom_id": str(CLASSROOM_ID)}),
        (AVAILABILITY_PATH, 500, 502, "UPSTREAM_UNAVAILABLE", {"upstream": "people-stub"}),
        (CLASSROOM_PATH, 503, 502, "UPSTREAM_UNAVAILABLE", {"upstream": "people-stub"}),
        (PROFILE_PATH, 403, 502, "UPSTREAM_UNAVAILABLE", {"upstream": "people-stub"}),
        (PROFILE_PATH, "network", 502, "UPSTREAM_UNAVAILABLE", {"upstream": "people-stub"}),
        (CLASSROOM_PATH, "invalid", 502, "UPSTREAM_UNAVAILABLE", {"upstream": "people-stub"}),
        (
            AVAILABILITY_PATH,
            "timeout",
            504,
            "UPSTREAM_TIMEOUT",
            {"upstream": "people-stub", "timeout_ms": 50},
        ),
    ],
)
async def test_people_error_response(
    failed_path: str, failure: int | str, status: int, code: str, details: dict[str, object]
) -> None:
    timed_out_request_finished = asyncio.Event()

    async def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path != failed_path:
            return httpx.Response(200, json=RESPONSES[request.url.path])
        if failure == "timeout":
            try:
                await asyncio.Event().wait()
            finally:
                timed_out_request_finished.set()
        if failure == "network":
            raise httpx.ConnectError("Connection refused", request=request)
        if failure == "invalid":
            return httpx.Response(200, json={**RESPONSES[CLASSROOM_PATH], "capacity": "30"})
        assert isinstance(failure, int)
        return httpx.Response(failure)

    async with httpx.AsyncClient(
        base_url="http://people.example", transport=httpx.MockTransport(transport)
    ) as upstream:
        client = PeopleClient(upstream, timeout_ms=50)
        app = FastAPI()
        install_error_handlers(app)

        @app.get("/test")
        async def collect() -> None:
            await collect_lesson_reference_data(
                client,
                lesson_format=LessonFormat.IN_PERSON,
                instructor_id=INSTRUCTOR_ID,
                classroom_id=CLASSROOM_ID,
            )

        async with httpx.AsyncClient(
            base_url="http://app.example", transport=httpx.ASGITransport(app=app)
        ) as http:
            async with asyncio.timeout(2):
                response = await http.get("/test")

    assert response.status_code == status
    error = response.json()["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert error["details"] == details
    assert isinstance(error["message"], str)
    if failure == "timeout":
        assert timed_out_request_finished.is_set()


async def test_lifespan_owns_people_client(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "http://configured-people.example:8100"
    monkeypatch.setenv("STUB_BASE_URL", url)
    monkeypatch.setenv("TEST_MODE", "1")
    get_settings.cache_clear()

    def reject(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected people-stub request: {request.url}")

    def make_client(*, base_url: str) -> httpx.AsyncClient:
        assert base_url == url
        return http

    app = create_app()
    http = httpx.AsyncClient(base_url=url, transport=httpx.MockTransport(reject))
    monkeypatch.setattr(main, "AsyncClient", make_client)
    try:
        async with lifespan(app):
            assert isinstance(app.state.context.people_client, PeopleClient)
            assert not http.is_closed

        assert http.is_closed
    finally:
        await http.aclose()
        get_settings.cache_clear()
