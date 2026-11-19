import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.people import PeopleClient
from app.context import AppContext
from app.db.models import Lesson
from app.enums.lessons import LessonFormat, LessonStatus
from tests.e2e.assignment import IDS
from tests.e2e.contract import ContractChecker
from tests.integration.maintenance.helpers import snapshot

_CREATE = "/lessons"
_VALIDATE = "/lessons/validate"
_POSTS = [_CREATE, _VALIDATE]
_EDIT = f"/lessons/{IDS['L1']}"
_BASE_BODY: dict[str, object] = {
    "group_id": IDS["G1"],
    "instructor_id": IDS["I1"],
    "classroom_id": IDS["C1"],
    "format": "IN_PERSON",
    "starts_at": "2026-12-02T12:00:00.123456+05:00",
    "ends_at": "2026-12-02T13:30:00.123456+05:00",
}


class Stub:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: dict[str, int | str] = {}
        self.capacity = 30
        self.limit = 6.0
        self.windows = [{"weekday": day, "from": "09:00", "to": "18:00"} for day in range(1, 6)]

    async def respond(self, request: httpx.Request) -> httpx.Response:
        _, resource, resource_id, *extra = request.url.path.split("/")
        endpoint = extra[0] if extra else resource
        self.calls.append(endpoint)
        failure = self.failures.get(endpoint)
        if failure == "timeout":
            await asyncio.Future()
        if isinstance(failure, int):
            return httpx.Response(failure)
        if endpoint == "classrooms":
            return httpx.Response(
                200,
                json={
                    "id": resource_id,
                    "name": "Ауд. 101",
                    "capacity": self.capacity,
                    "online_capable": False,
                },
            )
        if endpoint == "availability":
            return httpx.Response(
                200,
                json={
                    "instructor_id": resource_id,
                    "timezone": "Asia/Yekaterinburg",
                    "windows": self.windows,
                },
            )
        return httpx.Response(
            200,
            json={
                "id": resource_id,
                "full_name": "Преподаватель",
                "timezone": "Asia/Yekaterinburg",
                "max_hours_per_day": self.limit,
            },
        )


@pytest.fixture
async def schedule_api(
    api_client: tuple[httpx.AsyncClient, AppContext],
) -> AsyncIterator[tuple[httpx.AsyncClient, AppContext, Stub]]:
    http, context = api_client
    stub = Stub()
    async with httpx.AsyncClient(
        base_url="http://people.test", transport=httpx.MockTransport(stub.respond)
    ) as upstream:
        context.people_client = PeopleClient(upstream, timeout_ms=100)
        yield http, context, stub


async def _snapshot(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, list[dict[str, object]]]:
    async with factory() as session:
        return await snapshot(session)


async def test_create_and_read_planned_lesson(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub], contract: ContractChecker
) -> None:
    http, context, stub = schedule_api
    context.clock.freeze(datetime(2026, 12, 4, 3, 0, 0, 123456, tzinfo=UTC))
    stub.capacity = 12  # Та же вместимость, что и размер G1.
    before = await _snapshot(context.session_factory)
    response = await http.post(_CREATE, json=_BASE_BODY)

    assert response.status_code == 201, response.text
    result = response.json()
    contract.assert_schema(result, "LessonWithWarnings")
    lesson = result["lesson"]
    assert UUID(lesson["id"]).version == 4
    assert lesson == {
        "id": lesson["id"],
        "group_id": IDS["G1"],
        "instructor_id": IDS["I1"],
        "classroom_id": IDS["C1"],
        "format": "IN_PERSON",
        "status": "PLANNED",
        "starts_at": "2026-12-02T07:00:00.123456Z",
        "ends_at": "2026-12-02T08:30:00.123456Z",
        "created_at": "2026-12-04T03:00:00.123456Z",
        "updated_at": "2026-12-04T03:00:00.123456Z",
        "rescheduled_from_id": None,
        "cancel_reason": None,
    }
    assert result["warnings"] == []
    fetched = await http.get(f"/lessons/{lesson['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == lesson
    assert sorted(stub.calls) == ["availability", "classrooms", "instructors"]
    after = await _snapshot(context.session_factory)
    assert len(after["lessons"]) == len(before["lessons"]) + 1


async def test_edit_merges_fields_and_excludes_the_original(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub], contract: ContractChecker
) -> None:
    http, context, stub = schedule_api
    stub.limit = 1.0
    before = (await http.get(_EDIT)).json()
    context.clock.freeze(datetime(2026, 12, 4, 3, 0, 0, 123456, tzinfo=UTC))

    response = await http.patch(_EDIT, json={"starts_at": "2026-12-01T10:30:00+05:00"})
    assert response.status_code == 200, response.text
    result = response.json()
    contract.assert_schema(result, "LessonWithWarnings")
    expected = {
        **before,
        "starts_at": "2026-12-01T05:30:00Z",
        "updated_at": "2026-12-04T03:00:00.123456Z",
    }
    assert result == {"lesson": expected, "warnings": []}
    assert sorted(stub.calls) == ["availability", "classrooms", "instructors"]

    stub.calls.clear()
    context.clock.freeze(datetime(2026, 12, 5, tzinfo=UTC))
    response = await http.patch(_EDIT, json={"format": "ONLINE", "classroom_id": None})
    assert response.status_code == 200, response.text
    result = response.json()
    contract.assert_schema(result, "LessonWithWarnings")
    expected.update(format="ONLINE", classroom_id=None, updated_at="2026-12-05T00:00:00Z")
    assert result == {"lesson": expected, "warnings": []}
    assert (await http.get(_EDIT)).json() == expected
    assert sorted(stub.calls) == ["availability", "instructors"]


async def test_edit_rescheduled_successor_preserves_predecessor(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
) -> None:
    http, _, _ = schedule_api
    path = f"/lessons/{IDS['L7']}"
    response = await http.patch(path, json={"instructor_id": IDS["I2"]})
    assert response.status_code == 200, response.text
    assert response.json()["lesson"]["rescheduled_from_id"] == IDS["L6"]
    assert response.json()["lesson"]["instructor_id"] == IDS["I2"]


@pytest.mark.parametrize(
    ("key", "current_status"),
    [
        ("L2", "CONFIRMED"),
        ("L5", "CANCELLED"),
        ("L6", "RESCHEDULED"),
        ("L8", "COMPLETED"),
        ("L_MISSING", None),
    ],
)
async def test_edit_checks_existence_and_status_before_rules(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    key: str,
    current_status: str | None,
) -> None:
    http, context, stub = schedule_api
    before = await _snapshot(context.session_factory)
    response = await http.patch(f"/lessons/{IDS[key]}", json={"ends_at": "2026-11-01T00:00:00Z"})
    if current_status is None:
        assert contract.assert_error(response, 404, "NOT_FOUND") == {"lesson_id": IDS[key]}
    else:
        assert contract.assert_error(response, 409, "LESSON_NOT_EDITABLE") == {
            "current_status": current_status
        }
    assert stub.calls == []
    assert await _snapshot(context.session_factory) == before


async def test_edit_reports_exact_conflicts_and_preserves_the_original(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub], contract: ContractChecker
) -> None:
    http, context, _ = schedule_api
    before = await _snapshot(context.session_factory)
    response = await http.patch(
        _EDIT, json={"starts_at": "2026-12-01T07:30:00Z", "ends_at": "2026-12-01T09:00:00Z"}
    )
    assert contract.assert_error(response, 409, "SCHEDULE_CONFLICT") == {
        "conflicts": [
            {
                "resource": "classroom",
                "lesson_id": IDS["L2"],
                "overlap": {"starts_at": "2026-12-01T07:30:00Z", "ends_at": "2026-12-01T08:30:00Z"},
            }
        ]
    }
    assert await _snapshot(context.session_factory) == before


async def test_edit_returns_both_warnings(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub], contract: ContractChecker
) -> None:
    http, _, stub = schedule_api
    stub.limit = 1.0
    stub.windows = []
    response = await http.patch(_EDIT, json={"classroom_id": IDS["C2"]})
    assert response.status_code == 200, response.text
    result = response.json()
    contract.assert_schema(result, "LessonWithWarnings")
    assert result["lesson"]["classroom_id"] == IDS["C2"]
    warnings = [(warning["code"], warning["details"]) for warning in result["warnings"]]
    assert warnings == [
        ("WORKLOAD_SOFT_LIMIT", {"date": "2026-12-01", "max_hours": 1.0, "planned_hours": 1.5}),
        ("INSTRUCTOR_UNAVAILABLE", {"instructor_id": IDS["I1"]}),
    ]
    assert (await http.get(_EDIT)).json() == result["lesson"]


@pytest.mark.parametrize(
    ("changes", "upstream_failure", "status", "code"),
    [
        ({"ends_at": "2026-12-01T05:05:00Z"}, None, 422, "VALIDATION_ERROR"),
        ({"format": "ONLINE"}, None, 422, "VALIDATION_ERROR"),
        ({"classroom_id": None}, None, 422, "CLASSROOM_REQUIRED"),
        ({"classroom_id": IDS["C2"]}, 500, 502, "UPSTREAM_UNAVAILABLE"),
        ({"classroom_id": IDS["C2"]}, "timeout", 504, "UPSTREAM_TIMEOUT"),
    ],
)
async def test_edit_failure_does_not_change_schedule(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    changes: dict[str, str | None],
    upstream_failure: int | str | None,
    status: int,
    code: str,
) -> None:
    http, context, stub = schedule_api
    if upstream_failure is not None:
        stub.failures["classrooms"] = upstream_failure
    before = await _snapshot(context.session_factory)
    response = await http.patch(_EDIT, json=changes)
    contract.assert_error(response, status, code)
    assert await _snapshot(context.session_factory) == before


@pytest.mark.parametrize("path", _POSTS)
@pytest.mark.parametrize(
    ("overrides", "status", "code", "field"),
    [
        ({"ends_at": 1796190000}, 400, "BAD_REQUEST", "ends_at"),
        ({"format": 1}, 400, "BAD_REQUEST", "format"),
        ({"starts_at": "2026-12-02T12:00:00"}, 422, "VALIDATION_ERROR", "starts_at"),
        (
            {"ends_at": "2026-12-02T12:29:00+05:00", "classroom_id": None},
            422,
            "VALIDATION_ERROR",
            "ends_at",
        ),
        ({"classroom_id": None, "group_id": str(uuid4())}, 422, "CLASSROOM_REQUIRED", None),
        ({"format": "ONLINE"}, 422, "VALIDATION_ERROR", "classroom_id"),
        ({"group_id": str(uuid4())}, 422, "GROUP_NOT_FOUND", "group_id"),
    ],
)
async def test_local_errors_precede_people(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    path: str,
    overrides: dict[str, object],
    status: int,
    code: str,
    field: str | None,
) -> None:
    http, context, stub = schedule_api
    before = await _snapshot(context.session_factory)
    response = await http.post(path, json={**_BASE_BODY, **overrides})

    details = contract.assert_error(response, status, code)
    if code == "BAD_REQUEST":
        assert {error["field"] for error in details["errors"]} == {field}
    elif code == "VALIDATION_ERROR":
        assert set(details["fields"]) == {field}
    elif code == "GROUP_NOT_FOUND":
        assert details == {"group_id": overrides["group_id"]}
    else:
        assert details == {}
    assert stub.calls == []
    assert await _snapshot(context.session_factory) == before


@pytest.mark.parametrize("path", _POSTS)
async def test_malformed_json_returns_400(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    path: str,
) -> None:
    http, _, stub = schedule_api
    response = await http.post(path, content=b"{", headers={"Content-Type": "application/json"})

    contract.assert_error(response, 400, "BAD_REQUEST")
    assert stub.calls == []


@pytest.mark.parametrize("path", _POSTS)
@pytest.mark.parametrize(
    ("failures", "status", "code", "expected"),
    [
        (
            {"instructors": 404, "classrooms": 404},
            422,
            "INSTRUCTOR_NOT_FOUND",
            {"instructor_id": IDS["I1"]},
        ),
        ({"classrooms": 404}, 422, "CLASSROOM_NOT_FOUND", {"classroom_id": IDS["C1"]}),
        (
            {"availability": 500, "instructors": 404},
            502,
            "UPSTREAM_UNAVAILABLE",
            {"upstream": "people-stub"},
        ),
        (
            {"classrooms": "timeout", "availability": 500, "instructors": 404},
            504,
            "UPSTREAM_TIMEOUT",
            {"upstream": "people-stub", "timeout_ms": 100},
        ),
    ],
)
async def test_upstream_failure_preserves_schedule(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    path: str,
    failures: dict[str, int | str],
    status: int,
    code: str,
    expected: dict[str, object],
) -> None:
    http, context, stub = schedule_api
    stub.failures = failures
    before = await _snapshot(context.session_factory)
    response = await http.post(path, json=_BASE_BODY)

    assert contract.assert_error(response, status, code) == expected
    assert sorted(stub.calls) == ["availability", "classrooms", "instructors"]
    assert await _snapshot(context.session_factory) == before


@pytest.mark.parametrize("capacity", [10, 30])
async def test_capacity_priority_and_exact_conflicts_on_both_routes(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    capacity: int,
) -> None:
    http, context, stub = schedule_api
    stub.capacity = capacity
    stub.windows = []
    before = await _snapshot(context.session_factory)
    body = {
        **_BASE_BODY,
        "starts_at": "2026-12-01T06:00:00.000001Z",
        "ends_at": "2026-12-01T07:15:00.000001Z",
    }

    created = await http.post(_CREATE, json=body)
    validated = await http.post(_VALIDATE, json=body)

    expected_code = "CLASSROOM_TOO_SMALL" if capacity == 10 else "SCHEDULE_CONFLICT"
    details = contract.assert_error(created, 409, expected_code)
    assert validated.status_code == 200
    contract.assert_schema(validated.json(), "ValidationResult")
    assert validated.json() == {
        "ok": False,
        "violations": [created.json()["error"]],
        "warnings": [],
    }
    if capacity == 10:
        assert details == {"capacity": 10, "group_size": 12}
    else:
        expected = [
            {
                "resource": resource,
                "lesson_id": IDS["L1"],
                "overlap": {
                    "starts_at": "2026-12-01T06:00:00.000001Z",
                    "ends_at": "2026-12-01T06:30:00Z",
                },
            }
            for resource in ("instructor", "classroom", "group")
        ]
        expected.append(
            {
                "resource": "classroom",
                "lesson_id": IDS["L2"],
                "overlap": {
                    "starts_at": "2026-12-01T07:00:00Z",
                    "ends_at": "2026-12-01T07:15:00.000001Z",
                },
            }
        )
        assert details == {"conflicts": expected}
    assert await _snapshot(context.session_factory) == before


async def test_online_conflict_matches_public_scenario(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub], contract: ContractChecker
) -> None:
    http, context, stub = schedule_api
    before = await _snapshot(context.session_factory)
    response = await http.post(
        _CREATE,
        json={
            "group_id": IDS["G3"],
            "instructor_id": IDS["I1"],
            "format": "ONLINE",
            "starts_at": "2026-12-01T06:00:00Z",
            "ends_at": "2026-12-01T07:00:00Z",
        },
    )

    assert contract.assert_error(response, 409, "SCHEDULE_CONFLICT") == {
        "conflicts": [
            {
                "resource": "instructor",
                "lesson_id": IDS["L1"],
                "overlap": {
                    "starts_at": "2026-12-01T06:00:00Z",
                    "ends_at": "2026-12-01T06:30:00Z",
                },
            }
        ],
    }
    assert sorted(stub.calls) == ["availability", "instructors"]
    assert await _snapshot(context.session_factory) == before


@pytest.mark.parametrize("status", list(LessonStatus))
async def test_conflicts_consider_only_active_statuses(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
    contract: ContractChecker,
    status: LessonStatus,
) -> None:
    http, context, _ = schedule_api
    start = datetime(2026, 12, 7, 5, tzinfo=UTC)
    async with context.session_factory.begin() as session:
        session.add(_online_lesson(start, start + timedelta(hours=1), status))
    before = await _snapshot(context.session_factory)
    response = await http.post(_VALIDATE, json=_online_body(start, start + timedelta(hours=1)))

    assert response.status_code == 200
    result = response.json()
    contract.assert_schema(result, "ValidationResult")
    if status in {LessonStatus.CANCELLED, LessonStatus.RESCHEDULED}:
        assert result == {"ok": True, "violations": [], "warnings": []}
    else:
        assert not result["ok"]
        assert result["violations"][0]["code"] == "SCHEDULE_CONFLICT"
    assert await _snapshot(context.session_factory) == before


async def test_touching_active_lesson_and_two_null_rooms(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
) -> None:
    http, _, _ = schedule_api
    touching = {
        **_BASE_BODY,
        "starts_at": "2026-12-01T06:30:00Z",
        "ends_at": "2026-12-01T07:00:00Z",
    }
    online = {
        **touching,
        "format": "ONLINE",
        "classroom_id": None,
        "starts_at": "2026-12-01T09:00:00Z",
        "ends_at": "2026-12-01T10:00:00Z",
    }
    for body in (touching, online):
        response = await http.post(_VALIDATE, json=body)
        assert response.status_code == 200
        assert response.json() == {"ok": True, "violations": [], "warnings": []}


async def test_warnings_split_local_days_and_allow_creation(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub], contract: ContractChecker
) -> None:
    http, context, stub = schedule_api
    stub.limit = 1.25
    start = datetime.fromisoformat("2026-12-07T23:30:00+05:00")
    end = start + timedelta(hours=2)
    midnight = start + timedelta(minutes=30)
    async with context.session_factory.begin() as session:
        session.add_all(
            [
                _online_lesson(start - timedelta(hours=2), start, LessonStatus.COMPLETED),
                _online_lesson(start, midnight, LessonStatus.CANCELLED),
                _online_lesson(midnight, end, LessonStatus.RESCHEDULED),
            ]
        )
    before = await _snapshot(context.session_factory)
    body = _online_body(start, end)

    validated = await http.post(_VALIDATE, json=body)

    assert validated.status_code == 200
    validated_body = validated.json()
    contract.assert_schema(validated_body, "ValidationResult")
    assert validated_body["ok"]
    assert validated_body["violations"] == []
    warnings = validated_body["warnings"]
    assert [(warning["code"], warning["details"]) for warning in warnings] == [
        ("WORKLOAD_SOFT_LIMIT", {"date": "2026-12-07", "max_hours": 1.25, "planned_hours": 2.5}),
        ("WORKLOAD_SOFT_LIMIT", {"date": "2026-12-08", "max_hours": 1.25, "planned_hours": 1.5}),
        ("INSTRUCTOR_UNAVAILABLE", {"instructor_id": IDS["I1"]}),
    ]
    assert await _snapshot(context.session_factory) == before

    created = await http.post(_CREATE, json=body)
    assert created.status_code == 201, created.text
    contract.assert_schema(created.json(), "LessonWithWarnings")
    assert created.json()["warnings"] == warnings
    async with context.session_factory() as session:
        lesson = await session.scalar(
            select(Lesson).where(Lesson.id == UUID(created.json()["lesson"]["id"]))
        )
        assert lesson is not None
        assert lesson.classroom_id is None


async def test_workload_includes_a_lesson_started_on_previous_local_day(
    schedule_api: tuple[httpx.AsyncClient, AppContext, Stub],
) -> None:
    http, context, stub = schedule_api
    stub.limit = 1.25
    start = datetime.fromisoformat("2026-12-08T01:00:00+05:00")
    async with context.session_factory.begin() as session:
        session.add(_online_lesson(start - timedelta(hours=2), start, LessonStatus.CONFIRMED))

    response = await http.post(_VALIDATE, json=_online_body(start, start + timedelta(minutes=30)))

    assert response.status_code == 200
    result = response.json()
    assert result["ok"]
    workload = result["warnings"][0]
    assert workload["code"] == "WORKLOAD_SOFT_LIMIT"
    assert workload["details"] == {"date": "2026-12-08", "max_hours": 1.25, "planned_hours": 1.5}


def _online_body(start: datetime, end: datetime) -> dict[str, str]:
    return {
        "group_id": IDS["G1"],
        "instructor_id": IDS["I1"],
        "format": "ONLINE",
        "starts_at": start.isoformat(),
        "ends_at": end.isoformat(),
    }


def _online_lesson(start: datetime, end: datetime, status: LessonStatus) -> Lesson:
    return Lesson(
        id=uuid4(),
        group_id=UUID(IDS["G1"]),
        instructor_id=UUID(IDS["I1"]),
        classroom_id=None,
        status=status,
        format=LessonFormat.ONLINE,
        starts_at=start,
        ends_at=end,
        rescheduled_from_id=None,
        cancel_reason=None,
        created_at=start,
        updated_at=start,
    )
