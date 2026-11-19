from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.clients.people_models import Availability, Classroom
from app.clock import to_iso_z
from app.db.models import Lesson
from app.db.repositories.groups import GroupRepository
from app.db.repositories.lessons import LessonRepository
from app.enums.lessons import LessonFormat
from app.services.exceptions.lessons import (
    ClassroomRequiredError,
    GroupNotFoundError,
    LessonConflictError,
    LessonValidationError,
)
from app.services.lesson_reference_data import (
    LessonReferenceData,
    PeopleReader,
    collect_lesson_reference_data,
)
from app.services.lesson_results import LessonViolation, LessonWarning

_DAY = timedelta(days=1)
_HOUR = timedelta(hours=1)
_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True)
class LessonCandidate:
    group_id: UUID
    instructor_id: UUID
    classroom_id: UUID | None
    format: LessonFormat
    starts_at: datetime
    ends_at: datetime

    def resources(self) -> dict[str, UUID]:
        return {
            kind: resource_id
            for kind, resource_id in (
                ("instructor", self.instructor_id),
                ("classroom", self.classroom_id),
                ("group", self.group_id),
            )
            if resource_id is not None
        }


async def check_lesson(
    candidate: LessonCandidate,
    *,
    groups: GroupRepository,
    lessons: LessonRepository,
    people: PeopleReader,
    lock_for_write: bool,
    exclude_lesson_id: UUID | None = None,
) -> list[LessonWarning]:
    """Проверить BR-01…BR-07 на сессии вызывающего сценария."""
    candidate = replace(
        candidate,
        starts_at=candidate.starts_at.astimezone(UTC),
        ends_at=candidate.ends_at.astimezone(UTC),
    )
    _check_interval_and_format(candidate)
    group_size, references = await _load_references(candidate, groups, people)
    _check_capacity(group_size, references.classroom)

    if lock_for_write:
        await lessons.lock_resources(candidate.resources().items())
    # Отдельный SELECT после ожидания блокировки видит уже зафиксированную запись конкурента.
    await _check_conflicts(candidate, lessons, exclude_lesson_id)
    return await _collect_warnings(candidate, lessons, references, exclude_lesson_id)


async def _load_references(
    candidate: LessonCandidate, groups: GroupRepository, people: PeopleReader
) -> tuple[int, LessonReferenceData]:

    group = await groups.get_by_id(candidate.group_id)
    if group is None:
        raise GroupNotFoundError(candidate.group_id)
    references = await collect_lesson_reference_data(
        people,
        lesson_format=candidate.format,
        instructor_id=candidate.instructor_id,
        classroom_id=candidate.classroom_id,
    )
    return group.size, references


def _check_capacity(group_size: int, classroom: Classroom | None) -> None:
    if classroom is not None and classroom.capacity < group_size:
        raise LessonConflictError(
            LessonViolation(
                "CLASSROOM_TOO_SMALL",
                "Аудитория мала для группы",
                {"capacity": classroom.capacity, "group_size": group_size},
            )
        )


async def _check_conflicts(
    candidate: LessonCandidate, lessons: LessonRepository, exclude_lesson_id: UUID | None
) -> None:
    overlaps = await lessons.find_conflicting(
        starts_at=candidate.starts_at,
        ends_at=candidate.ends_at,
        instructor_id=candidate.instructor_id,
        classroom_id=candidate.classroom_id,
        group_id=candidate.group_id,
        exclude_lesson_id=exclude_lesson_id,
    )
    _reject_conflicts(candidate, overlaps)


async def _collect_warnings(
    candidate: LessonCandidate,
    lessons: LessonRepository,
    references: LessonReferenceData,
    exclude_lesson_id: UUID | None,
) -> list[LessonWarning]:
    starts_at, ends_at = candidate.starts_at, candidate.ends_at
    days = _workload_days(starts_at, ends_at, ZoneInfo(references.instructor.timezone))
    instructor_lessons = await lessons.find_instructor_lessons(
        candidate.instructor_id, days[0][1], days[-1][2], exclude_lesson_id
    )
    warnings = _workload_warnings(
        starts_at, ends_at, references.instructor.max_hours_per_day, days, instructor_lessons
    )
    if not _within_availability(starts_at, ends_at, references.availability):
        warnings.append(
            LessonWarning(
                "INSTRUCTOR_UNAVAILABLE",
                "Занятие вне окон доступности преподавателя",
                {"instructor_id": str(candidate.instructor_id)},
            )
        )
    return warnings


def _check_interval_and_format(candidate: LessonCandidate) -> None:
    duration = candidate.ends_at - candidate.starts_at
    if duration <= timedelta():
        raise LessonValidationError("ends_at", "Должно быть позже starts_at")
    if not timedelta(minutes=30) <= duration <= timedelta(hours=8):
        raise LessonValidationError("ends_at", "Длительность должна быть от 30 минут до 8 часов")
    if candidate.format is LessonFormat.IN_PERSON and candidate.classroom_id is None:
        raise ClassroomRequiredError()
    if candidate.format is LessonFormat.ONLINE and candidate.classroom_id is not None:
        raise LessonValidationError("classroom_id", "Для онлайн-занятия должно быть null")


def _reject_conflicts(candidate: LessonCandidate, overlaps: Sequence[Lesson]) -> None:
    resources = candidate.resources()
    conflicts = []
    for lesson in overlaps:
        overlap = {
            "starts_at": to_iso_z(
                max(candidate.starts_at, lesson.starts_at), preserve_fraction=True
            ),
            "ends_at": to_iso_z(min(candidate.ends_at, lesson.ends_at), preserve_fraction=True),
        }
        for kind, other_id in (
            ("instructor", lesson.instructor_id),
            ("classroom", lesson.classroom_id),
            ("group", lesson.group_id),
        ):
            if kind in resources and resources[kind] == other_id:
                conflicts.append(
                    {"resource": kind, "lesson_id": str(lesson.id), "overlap": overlap}
                )
    if conflicts:
        raise LessonConflictError(
            LessonViolation(
                "SCHEDULE_CONFLICT", "Пересечение с другим занятием", {"conflicts": conflicts}
            )
        )


def _workload_days(
    starts_at: datetime, ends_at: datetime, zone: ZoneInfo
) -> list[tuple[date, datetime, datetime]]:
    day = starts_at.astimezone(zone).date()
    last_day = (ends_at - _MICROSECOND).astimezone(zone).date()
    days = []
    while day <= last_day:
        day_start = datetime.combine(day, time.min, zone).astimezone(UTC)
        next_day = day + _DAY
        day_end = datetime.combine(next_day, time.min, zone).astimezone(UTC)
        if max(starts_at, day_start) < min(ends_at, day_end):
            days.append((day, day_start, day_end))
        day = next_day
    return days


def _workload_warnings(
    starts_at: datetime,
    ends_at: datetime,
    max_hours: float,
    days: Sequence[tuple[date, datetime, datetime]],
    existing: Sequence[Lesson],
) -> list[LessonWarning]:
    limit = Decimal(str(max_hours)) * (_HOUR // _MICROSECOND)
    intervals = [(lesson.starts_at, lesson.ends_at) for lesson in existing]
    intervals.append((starts_at, ends_at))
    warnings = []
    for day, day_start, day_end in days:
        duration = sum(
            (
                max(timedelta(), min(end, day_end) - max(start, day_start))
                for start, end in intervals
            ),
            timedelta(),
        )
        if duration // _MICROSECOND > limit:
            warnings.append(
                LessonWarning(
                    "WORKLOAD_SOFT_LIMIT",
                    "Превышена дневная норма преподавателя",
                    {
                        "date": day.isoformat(),
                        "max_hours": max_hours,
                        "planned_hours": duration / _HOUR,
                    },
                )
            )
    return warnings


def _within_availability(
    starts_at: datetime, ends_at: datetime, availability: Availability
) -> bool:
    zone = ZoneInfo(availability.timezone)
    last_instant = ends_at - _MICROSECOND
    points = _local_interval_endpoints(starts_at, last_instant, zone)
    day = points[0].date()
    if any(point.date() != day for point in points):
        return False
    for window in availability.windows:
        if window.weekday != day.isoweekday():
            continue
        window_start = time.fromisoformat(window.starts_at)
        window_end = time.fromisoformat(window.ends_at)
        if all(window_start <= point.time() < window_end for point in points):
            return True
    return False


def _local_interval_endpoints(
    start: datetime, last: datetime, zone: ZoneInfo
) -> tuple[datetime, ...]:
    first_local = start.astimezone(zone)
    last_local = last.astimezone(zone)
    if first_local.utcoffset() == last_local.utcoffset():
        return first_local, last_local

    # При смене смещения проверяем также обе стороны перехода. По одним концам
    # занятия вокруг осеннего перевода часов можно пропустить недоступный отрезок.
    before, after = start, last
    old_offset = first_local.utcoffset()
    while after - before > _MICROSECOND:
        middle = before + (after - before) // 2
        if middle.astimezone(zone).utcoffset() == old_offset:
            before = middle
        else:
            after = middle
    return first_local, before.astimezone(zone), after.astimezone(zone), last_local
