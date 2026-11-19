from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.people_models import Availability
from app.db.models import Group, Lesson
from app.db.repositories.groups import GroupRepository
from app.db.repositories.lessons import LessonRepository
from app.enums.lessons import LessonFormat
from app.services.exceptions import (
    ClassroomRequiredError,
    GroupNotFoundError,
    LessonValidationError,
)
from app.services.lesson_rules import (
    LessonCandidate,
    _within_availability,
    _workload_days,
    _workload_warnings,
    check_lesson,
)
from tests.unit.test_lesson_reference_data import FakePeople

START = datetime(2026, 12, 1, 5, tzinfo=UTC)
ONLINE = LessonCandidate(
    uuid4(), uuid4(), None, LessonFormat.ONLINE, START, START + timedelta(hours=1)
)


@pytest.mark.parametrize("minutes", [-1, 0, 29, 481])
async def test_invalid_duration_precedes_format_and_group(minutes: int) -> None:
    candidate = replace(
        ONLINE, format=LessonFormat.IN_PERSON, ends_at=START + timedelta(minutes=minutes)
    )
    people = FakePeople(delay=0)
    session = AsyncSession()
    with pytest.raises(LessonValidationError) as error:
        await check_lesson(
            candidate,
            groups=GroupRepository(session),
            lessons=LessonRepository(session),
            people=people,
            lock_for_write=True,
        )
    assert set(error.value.fields) == {"ends_at"}
    assert people.calls == []


@pytest.mark.parametrize("lesson_format", list(LessonFormat))
async def test_invalid_format_precedes_group_and_people(lesson_format: LessonFormat) -> None:
    classroom = uuid4() if lesson_format == LessonFormat.ONLINE else None
    candidate = replace(ONLINE, format=lesson_format, classroom_id=classroom)
    people = FakePeople(delay=0)
    session = AsyncSession()
    expected = LessonValidationError if classroom is not None else ClassroomRequiredError
    with pytest.raises(expected):
        await check_lesson(
            candidate,
            groups=GroupRepository(session),
            lessons=LessonRepository(session),
            people=people,
            lock_for_write=True,
        )
    assert people.calls == []


async def test_missing_group_precedes_people(monkeypatch: pytest.MonkeyPatch) -> None:
    people = FakePeople(delay=0)
    session = AsyncSession()
    groups = GroupRepository(session)
    monkeypatch.setattr(groups, "get_by_id", AsyncMock(return_value=None))

    with pytest.raises(GroupNotFoundError) as error:
        await check_lesson(
            ONLINE,
            groups=groups,
            lessons=LessonRepository(session),
            people=people,
            lock_for_write=True,
        )

    assert error.value.group_id == ONLINE.group_id
    assert people.calls == []


@pytest.mark.parametrize("minutes", [30, 480])
async def test_duration_limits_pass(minutes: int, monkeypatch: pytest.MonkeyPatch) -> None:
    people = FakePeople(delay=0)
    session = AsyncSession()
    groups = GroupRepository(session)
    lessons = LessonRepository(session)
    candidate = replace(ONLINE, ends_at=START + timedelta(minutes=minutes))
    group = Group(id=candidate.group_id, name="Группа", size=12)
    monkeypatch.setattr(groups, "get_by_id", AsyncMock(return_value=group))
    monkeypatch.setattr(lessons, "find_conflicting", AsyncMock(return_value=[]))
    monkeypatch.setattr(lessons, "find_instructor_lessons", AsyncMock(return_value=[]))

    await check_lesson(
        candidate, groups=groups, lessons=lessons, people=people, lock_for_write=False
    )

    assert sorted(people.calls) == ["availability", "profile"]


def test_local_workload_splits_both_new_and_existing_lessons() -> None:
    zone = ZoneInfo("Asia/Yekaterinburg")
    start = datetime.fromisoformat("2026-12-01T23:30:00+05:00").astimezone(UTC)
    end = start + timedelta(minutes=90)
    existing = Lesson(
        starts_at=datetime.fromisoformat("2026-12-01T21:00:00+05:00"),
        ends_at=datetime.fromisoformat("2026-12-01T23:30:00+05:00"),
    )
    following = Lesson(starts_at=end, ends_at=end + timedelta(hours=2))
    days = _workload_days(start, end, zone)
    warnings = _workload_warnings(start, end, 2.5, days, [existing, following])

    assert [warning.details for warning in warnings] == [
        {"date": "2026-12-01", "max_hours": 2.5, "planned_hours": 3.0},
        {"date": "2026-12-02", "max_hours": 2.5, "planned_hours": 3.0},
    ]
    assert _workload_warnings(start, end, 3, days, [existing, following]) == []


def test_workload_uses_elapsed_time_on_a_day_with_offset_change() -> None:
    zone = ZoneInfo("Europe/Berlin")
    start = datetime.fromisoformat("2026-10-25T01:30:00+02:00").astimezone(UTC)
    end = datetime.fromisoformat("2026-10-25T03:30:00+01:00").astimezone(UTC)
    days = _workload_days(start, end, zone)

    assert days[0][2] - days[0][1] == timedelta(hours=25)
    assert _workload_warnings(start, end, 2.5, days, [])[0].details["planned_hours"] == 3


def test_workload_ending_at_midnight_skips_next_day() -> None:
    zone = ZoneInfo("Asia/Yekaterinburg")
    end = datetime.fromisoformat("2026-12-02T00:00:00+05:00").astimezone(UTC)
    start = end - timedelta(hours=1)
    days = _workload_days(start, end, zone)

    assert [day.isoformat() for day, _, _ in days] == ["2026-12-01"]


@pytest.mark.parametrize(
    ("start", "end", "covered"),
    [
        ("2026-12-01T09:00:00+05:00", "2026-12-01T12:00:00+05:00", True),
        ("2026-12-01T11:30:00+05:00", "2026-12-01T12:30:00+05:00", False),
        ("2026-12-01T08:59:59.999999+05:00", "2026-12-01T09:30:00+05:00", False),
        ("2026-12-01T23:30:00+05:00", "2026-12-02T00:30:00+05:00", False),
        ("2026-12-02T09:00:00+05:00", "2026-12-02T12:00:00+05:00", False),
    ],
)
def test_availability_requires_one_containing_window(start: str, end: str, covered: bool) -> None:
    availability = Availability.model_validate(
        {
            "instructor_id": ONLINE.instructor_id,
            "timezone": "Asia/Yekaterinburg",
            "windows": [
                {"weekday": 2, "from": "09:00", "to": "12:00"},
                {"weekday": 2, "from": "12:00", "to": "15:00"},
            ],
        }
    )
    starts_at = datetime.fromisoformat(start).astimezone(UTC)
    ends_at = datetime.fromisoformat(end).astimezone(UTC)

    assert _within_availability(starts_at, ends_at, availability) is covered


@pytest.mark.parametrize(
    ("start", "end", "window", "covered"),
    [
        ("2026-03-29T03:00:00+02:00", "2026-03-29T03:30:00+02:00", ("02:30", "04:00"), True),
        ("2026-10-25T02:45:00+02:00", "2026-10-25T02:45:00+01:00", ("02:15", "03:30"), False),
        ("2026-10-25T02:15:00+01:00", "2026-10-25T02:45:00+01:00", ("02:15", "02:45"), True),
    ],
)
def test_availability_uses_local_times_when_offset_changes(
    start: str, end: str, window: tuple[str, str], covered: bool
) -> None:
    availability = Availability.model_validate(
        {
            "instructor_id": ONLINE.instructor_id,
            "timezone": "Europe/Berlin",
            "windows": [{"weekday": 7, "from": window[0], "to": window[1]}],
        }
    )
    starts_at = datetime.fromisoformat(start).astimezone(UTC)
    ends_at = datetime.fromisoformat(end).astimezone(UTC)

    assert _within_availability(starts_at, ends_at, availability) is covered
