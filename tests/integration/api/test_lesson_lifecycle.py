import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import aio_pika
import httpx
import pytest
import yaml
from aio_pika.exceptions import AuthenticationError
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy import update

from app.broker import RabbitMQBroker
from app.clock import to_iso_z
from app.context import AppContext
from app.db.models import Lesson
from app.db.session import session_scope
from app.enums.lessons import LessonStatus
from app.schemas.lesson_events import PublishedLessonEvent
from tests.e2e.assignment import IDS
from tests.e2e.contract import ContractChecker
from tests.integration.api.test_schedule import Stub, _snapshot
from tests.integration.api.test_schedule import schedule_api as schedule_api

_LESSON = f"/lessons/{IDS['L1']}"
_START = datetime(2026, 12, 1, 5, tzinfo=UTC)
_END = _START + timedelta(minutes=90)
_NOW = datetime(2026, 12, 4, 3, 0, 0, 123456, tzinfo=UTC)
_INTERVAL = {"starts_at": to_iso_z(_START), "ends_at": to_iso_z(_END)}
_SWEEPER = "/__test/jobs/lesson-status-sweeper/run"
_TRANSITIONS = [
    ("confirm", LessonStatus.CONFIRMED, {LessonStatus.PLANNED}),
    ("cancel", LessonStatus.CANCELLED, {LessonStatus.PLANNED, LessonStatus.CONFIRMED}),
    ("reschedule", LessonStatus.RESCHEDULED, {LessonStatus.PLANNED, LessonStatus.CONFIRMED}),
    ("complete", LessonStatus.COMPLETED, {LessonStatus.IN_PROGRESS}),
]


@pytest.fixture(scope="module")
def asyncapi_registry() -> Registry[bool | Mapping[str, Any]]:
    spec_path = Path(__file__).resolve().parents[3] / "asyncapi.yaml"
    document = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    resource = Resource.from_contents(document, default_specification=DRAFT202012)
    registry: Registry[bool | Mapping[str, Any]] = Registry().with_resource(
        "asyncapi.yaml", resource
    )
    return registry


@pytest.mark.parametrize(
    ("action", "event_type", "key_prefix"),
    [
        ("confirm", "LessonConfirmed", "lesson-confirmed"),
        ("cancel", "LessonCancelled", "lesson-cancelled"),
        ("reschedule", "LessonRescheduled", "lesson-rescheduled"),
    ],
)
async def test_lifecycle_event_matches_asyncapi_and_transition(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    asyncapi_registry: Registry[bool | Mapping[str, Any]],
    action: str,
    event_type: str,
    key_prefix: str,
) -> None:
    http, context, _ = schedule_api
    if action == "cancel":
        assert (await http.post(f"{_LESSON}/confirm")).status_code == 200
    original = (await http.get(_LESSON)).json()
    context.clock.freeze(_NOW)
    events: list[PublishedLessonEvent] = []

    class RecordingPublisher:
        async def publish(self, event: PublishedLessonEvent) -> None:
            events.append(event)

    context.event_publisher = RecordingPublisher()
    expected = {
        "lesson_id": original["id"],
        "group_id": original["group_id"],
        "instructor_id": original["instructor_id"],
    }
    previous = {
        field: original[field]
        for field in ("starts_at", "ends_at", "instructor_id", "classroom_id")
    }
    if action == "reschedule":
        response = await http.post(
            f"{_LESSON}/reschedule",
            json={
                **_INTERVAL,
                "instructor_id": IDS["I2"],
                "format": "ONLINE",
                "classroom_id": None,
            },
        )
        assert response.status_code == 201, response.text
        successor = response.json()["lesson"]
        expected.update(
            rescheduled_to_id=successor["id"],
            previous=previous,
            new={**_INTERVAL, "instructor_id": IDS["I2"], "classroom_id": None},
        )
    else:
        response = await http.post(f"{_LESSON}/{action}")
        assert response.status_code == 200, response.text
        expected.update(_INTERVAL)
        if action == "cancel":
            expected.update(previous_status="CONFIRMED", reason=None)
        else:
            expected.update(classroom_id=original["classroom_id"], format=original["format"])

    (event,) = events
    wire = json.loads(event.model_dump_json())
    validator = Draft202012Validator(
        {"$ref": f"asyncapi.yaml#/components/messages/{event_type}/payload"},
        registry=asyncapi_registry,
        format_checker=FormatChecker(),
    )
    validator.validate(wire)
    assert wire == {
        "event_id": str(event.event_id),
        "event_type": event_type,
        "occurred_at": to_iso_z(_NOW),
        "idempotency_key": f"{key_prefix}:{original['id']}",
        "producer": "timetable-service",
        "version": 1,
        "payload": expected,
    }
    assert event.event_id.version == 4


async def test_publication_failure_preserves_successful_http_result(
    api_client: tuple[httpx.AsyncClient, AppContext],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    http, context = api_client
    context.event_publisher = RabbitMQBroker("amqp://example.test/")
    connect = AsyncMock(side_effect=AuthenticationError())
    monkeypatch.setattr(aio_pika, "connect", connect)

    response = await http.post(f"{_LESSON}/confirm")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "CONFIRMED"
    assert (await http.get(_LESSON)).json() == response.json()
    connect.assert_awaited_once()
    assert sum("RabbitMQ publication not sent" in record.message for record in caplog.records) == 1


async def test_confirm_persists_and_rejects_repeat(
    api_client: tuple[httpx.AsyncClient, AppContext], contract: ContractChecker
) -> None:
    http, context = api_client
    original = (await http.get(_LESSON)).json()
    context.clock.freeze(_NOW)
    response = await http.post(f"{_LESSON}/confirm")

    assert response.status_code == 200, response.text
    body = response.json()
    contract.assert_schema(body, "Lesson")
    assert body == {
        **original,
        "status": "CONFIRMED",
        "updated_at": to_iso_z(_NOW, preserve_fraction=True),
    }
    assert (await http.get(_LESSON)).json() == body

    repeat = await http.post(f"{_LESSON}/confirm")
    assert repeat.status_code == 409
    assert repeat.json()["error"] == {
        "code": "TRANSITION_FORBIDDEN",
        "message": "Недопустимый переход",
        "details": {"current_status": "CONFIRMED", "target_status": "CONFIRMED"},
    }


@pytest.mark.parametrize(
    ("method", "target", "current"),
    [
        (method, target, current)
        for method, target, allowed in _TRANSITIONS
        for current in LessonStatus
        if current not in allowed
    ],
)
async def test_reject_forbidden_transitions_before_business_rules(
    api_client: tuple[httpx.AsyncClient, AppContext],
    method: str,
    target: LessonStatus,
    current: LessonStatus,
) -> None:
    http, context = api_client
    async with session_scope(context.session_factory) as session:
        await session.execute(
            update(Lesson).where(Lesson.id == UUID(IDS["L1"])).values(status=current)
        )
    context.clock.freeze(_START)
    before = await _snapshot(context.session_factory)
    url = f"{_LESSON}/{method}"
    response = (
        await http.post(url, json={"starts_at": to_iso_z(_START), "ends_at": to_iso_z(_START)})
        if method == "reschedule"
        else await http.post(url)
    )

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "TRANSITION_FORBIDDEN"
    assert error["details"] == {"current_status": current, "target_status": target}
    assert await _snapshot(context.session_factory) == before


@pytest.mark.parametrize("method", ["confirm", "cancel", "reschedule", "complete"])
async def test_lifecycle_missing_lesson(
    api_client: tuple[httpx.AsyncClient, AppContext], method: str
) -> None:
    http, _ = api_client
    lesson_id = str(uuid4())
    url = f"/lessons/{lesson_id}/{method}"
    response = (
        await http.post(url, json=_INTERVAL) if method == "reschedule" else await http.post(url)
    )
    assert response.status_code == 404, response.text
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["details"] == {"lesson_id": lesson_id}


@pytest.mark.parametrize(
    ("lesson", "body", "reason"),
    [
        ("L1", None, None),
        ("L2", {}, None),
        ("L1", {"reason": None}, None),
        ("L2", {"reason": ""}, ""),
        ("L1", {"reason": " " + "я" * 499}, " " + "я" * 499),
    ],
)
async def test_cancel_persists_optional_reason(
    api_client: tuple[httpx.AsyncClient, AppContext],
    contract: ContractChecker,
    lesson: str,
    body: dict[str, str | None] | None,
    reason: str | None,
) -> None:
    http, context = api_client
    url = f"/lessons/{IDS[lesson]}"
    original = (await http.get(url)).json()
    context.clock.freeze(_START)
    response = (
        await http.post(f"{url}/cancel")
        if body is None
        else await http.post(f"{url}/cancel", json=body)
    )

    assert response.status_code == 200, response.text
    cancelled = response.json()
    contract.assert_schema(cancelled, "Lesson")
    assert cancelled == {
        **original,
        "status": "CANCELLED",
        "cancel_reason": reason,
        "updated_at": to_iso_z(_START),
    }
    assert (await http.get(url)).json() == cancelled


async def test_complete_at_end_after_rejection_one_microsecond_early(
    api_client: tuple[httpx.AsyncClient, AppContext], contract: ContractChecker
) -> None:
    http, context = api_client
    await http.post(f"{_LESSON}/confirm")
    context.clock.freeze(_END - timedelta(microseconds=1))
    assert (await http.post(_SWEEPER)).json() == {"processed": 2}
    original = (await http.get(_LESSON)).json()
    response = await http.post(f"{_LESSON}/complete")

    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "LESSON_NOT_FINISHED"
    assert error["details"] == {"ends_at": to_iso_z(_END), "now": "2026-12-01T06:29:59.999999Z"}
    assert (await http.get(_LESSON)).json() == original

    context.clock.freeze(_END)
    response = await http.post(f"{_LESSON}/complete")
    assert response.status_code == 200, response.text
    completed = response.json()
    contract.assert_schema(completed, "Lesson")
    assert completed == {**original, "status": "COMPLETED", "updated_at": to_iso_z(_END)}
    assert (await http.get(_LESSON)).json() == completed


@pytest.mark.parametrize("online", [False, True])
async def test_reschedule_inherits_or_clears_and_excludes_original(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    online: bool,
) -> None:
    http, context, stub = schedule_api
    if online:
        assert (await http.post(f"{_LESSON}/confirm")).status_code == 200
    original = (await http.get(_LESSON)).json()
    context.clock.freeze(_NOW)
    stub.limit = 1.5
    body: dict[str, str | None] = dict(_INTERVAL)
    if online:
        body.update(format="ONLINE", classroom_id=None)
    response = await http.post(f"{_LESSON}/reschedule", json=body)

    assert response.status_code == 201, response.text
    result = response.json()
    contract.assert_schema(result, "LessonWithWarnings")
    assert result["warnings"] == []
    successor = result["lesson"]
    assert successor["id"] != original["id"]
    moment = to_iso_z(_NOW, preserve_fraction=True)
    assert successor == {
        **original,
        "id": successor["id"],
        "status": "PLANNED",
        "rescheduled_from_id": original["id"],
        "format": "ONLINE" if online else original["format"],
        "classroom_id": None if online else original["classroom_id"],
        "created_at": moment,
        "updated_at": moment,
    }
    assert (await http.get(f"/lessons/{successor['id']}")).json() == successor
    assert (await http.get(_LESSON)).json() == {
        **original,
        "status": "RESCHEDULED",
        "updated_at": moment,
    }
    calls = stub.calls.copy()
    repeat = await http.post(f"{_LESSON}/reschedule", json=body)
    assert repeat.status_code == 409
    assert repeat.json()["error"]["details"] == {
        "current_status": "RESCHEDULED",
        "target_status": "RESCHEDULED",
    }
    assert stub.calls == calls
    after = await _snapshot(context.session_factory)
    assert [
        row["id"] for row in after["lessons"] if row["rescheduled_from_id"] == original["id"]
    ] == [
        successor["id"],
    ]


async def test_reschedule_returns_warnings(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
) -> None:
    http, _, stub = schedule_api
    stub.limit = 1.0
    stub.windows = []
    response = await http.post(f"{_LESSON}/reschedule", json=_INTERVAL)

    assert response.status_code == 201, response.text
    warnings = response.json()["warnings"]
    assert [warning["code"] for warning in warnings] == [
        "WORKLOAD_SOFT_LIMIT",
        "INSTRUCTOR_UNAVAILABLE",
    ]
    assert warnings[0]["details"]["planned_hours"] == 1.5


@pytest.mark.parametrize(
    ("changes", "upstream", "status", "code"),
    [
        ({"ends_at": _INTERVAL["starts_at"]}, None, 422, "VALIDATION_ERROR"),
        ({"format": "ONLINE"}, None, 422, "VALIDATION_ERROR"),
        ({"classroom_id": None}, None, 422, "CLASSROOM_REQUIRED"),
        (
            {"starts_at": "2026-12-01T07:00:00Z", "ends_at": "2026-12-01T08:00:00Z"},
            None,
            409,
            "SCHEDULE_CONFLICT",
        ),
        ({}, 503, 502, "UPSTREAM_UNAVAILABLE"),
        ({}, "timeout", 504, "UPSTREAM_TIMEOUT"),
    ],
)
async def test_reschedule_failure_preserves_schedule(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    changes: dict[str, object],
    upstream: int | str | None,
    status: int,
    code: str,
) -> None:
    http, context, stub = schedule_api
    if upstream is not None:
        stub.failures["instructors"] = upstream
    before = await _snapshot(context.session_factory)
    response = await http.post(f"{_LESSON}/reschedule", json={**_INTERVAL, **changes})

    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert await _snapshot(context.session_factory) == before


async def test_manual_sweeper_updates_only_due_confirmed_lessons_once(
    api_client: tuple[httpx.AsyncClient, AppContext],
) -> None:
    http, context = api_client
    assert (await http.post(f"{_LESSON}/confirm")).status_code == 200
    context.clock.freeze(_START)
    before = await _snapshot(context.session_factory)
    first = await http.post(_SWEEPER)
    assert first.status_code == 200, first.text
    assert first.json() == {"processed": 2}

    after = await _snapshot(context.session_factory)
    assert after["lessons"] == [
        {**row, "status": "IN_PROGRESS", "updated_at": to_iso_z(_START)}
        if row["id"] in (IDS["L1"], IDS["L4"])
        else row
        for row in before["lessons"]
    ]
    second = await http.post(_SWEEPER)
    assert second.status_code == 200
    assert second.json() == {"processed": 0}
    assert await _snapshot(context.session_factory) == after
