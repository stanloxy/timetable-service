from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.clock import AdjustableClock
from app.db.models import Group, Lesson
from app.enums.lessons import LessonFormat, LessonStatus
from app.schemas.lesson_events import LessonRescheduledPayload, PublishedLessonEvent
from app.schemas.lessons import LessonReschedule
from app.services.exceptions.lessons import (
    LessonConflictError,
    LessonNotEditableError,
    LessonTransitionForbiddenError,
)
from app.services.lesson_rules import LessonCandidate
from app.services.lessons import LessonService
from tests.integration.db.helpers import AbortWriteCommit, run_write_race
from tests.unit.test_lesson_reference_data import FakePeople

# Predates all seed lessons, so a committed sweep can be limited to test-owned rows by its cutoff.
_START = datetime(2000, 1, 3, 5, tzinfo=UTC)
_HOUR = timedelta(hours=1)
_NEW_INTERVAL: LessonReschedule = {
    "starts_at": _START + 4 * _HOUR,
    "ends_at": _START + 5 * _HOUR,
}


@pytest.fixture
def clock() -> AdjustableClock:
    result = AdjustableClock()
    result.freeze(_START)
    return result


@pytest.fixture
async def racing_lessons(
    db_engine: AsyncEngine, clock: AdjustableClock
) -> AsyncIterator[tuple[Lesson, Lesson]]:
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    groups = [uuid4(), uuid4()]
    first = LessonCandidate(groups[0], uuid4(), None, LessonFormat.ONLINE, _START, _START + _HOUR)
    second = replace(
        first,
        group_id=groups[1],
        instructor_id=uuid4(),
        starts_at=_START + 2 * _HOUR,
        ends_at=_START + 3 * _HOUR,
    )
    people = FakePeople(delay=0)
    service = LessonService(sessions)
    try:
        async with sessions.begin() as session:
            session.add_all(Group(id=group, name="Группа переходов", size=10) for group in groups)
        original, _ = await service.create(first, people=people, clock=clock)
        other, _ = await service.create(second, people=people, clock=clock)
        yield original, other
    finally:
        async with sessions.begin() as session:
            await session.execute(delete(Lesson).where(Lesson.group_id.in_(groups)))
            await session.execute(delete(Group).where(Group.id.in_(groups)))


async def _read(engine: AsyncEngine, lesson_id: UUID) -> Lesson:
    return await LessonService(async_sessionmaker(engine, expire_on_commit=False)).get_by_id(
        lesson_id
    )


async def _successors(engine: AsyncEngine, lesson_id: UUID) -> list[UUID]:
    async with AsyncSession(engine) as session:
        ids = await session.scalars(
            select(Lesson.id).where(Lesson.rescheduled_from_id == lesson_id)
        )
        return list(ids)


def _assert_transition_rejected(error: object, current: LessonStatus, target: LessonStatus) -> None:
    assert isinstance(error, LessonTransitionForbiddenError)
    assert (error.current_status, error.target_status) == (current, target)


async def _confirm_only_due_lesson(
    engine: AsyncEngine, lesson: Lesson, clock: AdjustableClock
) -> None:
    async with AsyncSession(engine) as session:
        due = await session.scalar(
            select(Lesson.id)
            .where(Lesson.status == LessonStatus.CONFIRMED, Lesson.starts_at <= clock.now())
            .limit(1)
        )
        assert due is None, "Committed sweep must only update a row owned by this test"
    await LessonService(async_sessionmaker(engine, expire_on_commit=False)).confirm(
        lesson.id, clock=clock
    )


@pytest.mark.parametrize(
    ("action", "target"),
    [
        ("confirm", LessonStatus.CONFIRMED),
        ("cancel", LessonStatus.CANCELLED),
        ("reschedule", LessonStatus.RESCHEDULED),
    ],
)
@pytest.mark.parametrize("abort", [False, True])
async def test_lifecycle_event_requires_commit(
    db_engine: AsyncEngine,
    racing_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    action: str,
    target: LessonStatus,
    abort: bool,
) -> None:
    original, _ = racing_lessons
    events: list[PublishedLessonEvent] = []

    class CheckingPublisher:
        async def publish(self, event: PublishedLessonEvent) -> None:
            # These reads use an independent session while the publisher is running.
            assert (await _read(db_engine, original.id)).status == target
            if isinstance(event.payload, LessonRescheduledPayload):
                successor = await _read(db_engine, event.payload.rescheduled_to_id)
                assert successor.status == LessonStatus.PLANNED
                assert successor.rescheduled_from_id == original.id
            events.append(event)

    class FailingCommitSession(AsyncSession):
        async def commit(self) -> None:
            await self.flush()
            raise AbortWriteCommit

    session_class = FailingCommitSession if abort else AsyncSession
    sessions = async_sessionmaker[AsyncSession](
        db_engine, class_=session_class, expire_on_commit=False
    )
    service = LessonService(sessions, event_publisher=CheckingPublisher())

    async def transition() -> None:
        if action == "confirm":
            await service.confirm(original.id, clock=clock)
        elif action == "cancel":
            await service.cancel(original.id, reason=None, clock=clock)
        else:
            await service.reschedule(
                original.id, _NEW_INTERVAL, people=FakePeople(delay=0), clock=clock
            )

    if abort:
        with pytest.raises(AbortWriteCommit):
            await transition()
        assert events == []
        saved = await _read(db_engine, original.id)
        assert saved.status == LessonStatus.PLANNED
        assert saved.updated_at == original.updated_at
        assert await _successors(db_engine, original.id) == []
    else:
        await transition()
        with pytest.raises(LessonTransitionForbiddenError):
            await transition()
        assert len(events) == 1
        assert events[0].payload.lesson_id == original.id


@pytest.mark.parametrize("abort", [False, True])
async def test_two_concurrent_reschedules_leave_one_successor(
    db_engine: AsyncEngine,
    racing_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    abort: bool,
) -> None:
    original, _ = racing_lessons
    people = FakePeople(delay=0)

    async def move(service: LessonService) -> Lesson:
        new, _ = await service.reschedule(original.id, _NEW_INTERVAL, people=people, clock=clock)
        return new

    first, second = await run_write_race(db_engine, move, move, abort=abort)
    if abort:
        assert isinstance(first, AbortWriteCommit)
        assert isinstance(second, Lesson)
        winner = second
    else:
        assert isinstance(first, Lesson)
        _assert_transition_rejected(second, LessonStatus.RESCHEDULED, LessonStatus.RESCHEDULED)
        winner = first
    assert await _successors(db_engine, original.id) == [winner.id]
    assert winner.status == LessonStatus.PLANNED
    assert (await _read(db_engine, original.id)).status == LessonStatus.RESCHEDULED


@pytest.mark.parametrize("competing_operation", ["create", "edit"])
@pytest.mark.parametrize("move_first", [False, True])
async def test_reschedule_serializes_with_post_and_patch_on_destination(
    db_engine: AsyncEngine,
    racing_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    competing_operation: str,
    move_first: bool,
) -> None:
    original, other = racing_lessons
    instructor = uuid4()
    target: LessonReschedule = {**_NEW_INTERVAL, "instructor_id": instructor}
    people = FakePeople(delay=0)

    async def move(service: LessonService) -> Lesson:
        lesson, _ = await service.reschedule(original.id, target, people=people, clock=clock)
        return lesson

    async def compete(service: LessonService) -> Lesson:
        if competing_operation == "edit":
            lesson, _ = await service.edit(
                other.id,
                {
                    "instructor_id": instructor,
                    "starts_at": target["starts_at"],
                    "ends_at": target["ends_at"],
                },
                people=people,
                clock=clock,
            )
        else:
            candidate = LessonCandidate(
                other.group_id,
                instructor,
                None,
                LessonFormat.ONLINE,
                target["starts_at"],
                target["ends_at"],
            )
            lesson, _ = await service.create(candidate, people=people, clock=clock)
        return lesson

    first, second = (move, compete) if move_first else (compete, move)
    winner, error = await run_write_race(db_engine, first, second)
    assert isinstance(winner, Lesson)
    assert isinstance(error, LessonConflictError)
    assert error.violation.code == "SCHEDULE_CONFLICT"
    assert error.violation.details["conflicts"] == [
        {
            "resource": "instructor",
            "lesson_id": str(winner.id),
            "overlap": {"starts_at": "2000-01-03T09:00:00Z", "ends_at": "2000-01-03T10:00:00Z"},
        }
    ]
    saved = await _read(db_engine, original.id)
    assert saved.status == (LessonStatus.RESCHEDULED if move_first else LessonStatus.PLANNED)
    assert await _successors(db_engine, original.id) == ([winner.id] if move_first else [])


@pytest.mark.parametrize("abort", [False, True])
async def test_reschedule_holds_old_resource_and_rollback_restores_original(
    db_engine: AsyncEngine,
    racing_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    abort: bool,
) -> None:
    original, other = racing_lessons
    people = FakePeople(delay=0)
    target: LessonReschedule = {**_NEW_INTERVAL, "instructor_id": uuid4()}
    candidate = LessonCandidate(
        other.group_id,
        original.instructor_id,
        None,
        LessonFormat.ONLINE,
        original.starts_at,
        original.ends_at,
    )
    clock.freeze(_START + 6 * _HOUR)

    async def move(service: LessonService) -> Lesson:
        lesson, _ = await service.reschedule(original.id, target, people=people, clock=clock)
        return lesson

    async def create(service: LessonService) -> Lesson:
        lesson, _ = await service.create(candidate, people=people, clock=clock)
        return lesson

    moved, created = await run_write_race(db_engine, move, create, abort=abort)
    saved = await _read(db_engine, original.id)
    if abort:
        assert isinstance(moved, AbortWriteCommit)
        assert isinstance(created, LessonConflictError)
        assert created.violation.code == "SCHEDULE_CONFLICT"
        assert saved.status == original.status
        assert saved.updated_at == original.updated_at
        assert await _successors(db_engine, original.id) == []
    else:
        assert isinstance(moved, Lesson)
        assert isinstance(created, Lesson)
        assert created.instructor_id == original.instructor_id
        assert saved.status == LessonStatus.RESCHEDULED
        assert saved.updated_at == clock.now()
        assert await _successors(db_engine, original.id) == [moved.id]
    assert (saved.starts_at, saved.ends_at, saved.instructor_id) == (
        original.starts_at,
        original.ends_at,
        original.instructor_id,
    )


@pytest.mark.parametrize("move_first", [False, True])
async def test_reschedule_and_patch_read_latest_row(
    db_engine: AsyncEngine,
    racing_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    move_first: bool,
) -> None:
    original, _ = racing_lessons
    people = FakePeople(delay=0)
    instructor = uuid4()

    async def move(service: LessonService) -> Lesson:
        lesson, _ = await service.reschedule(original.id, _NEW_INTERVAL, people=people, clock=clock)
        return lesson

    async def patch(service: LessonService) -> Lesson:
        lesson, _ = await service.edit(
            original.id, {"instructor_id": instructor}, people=people, clock=clock
        )
        return lesson

    first, second = (move, patch) if move_first else (patch, move)
    result, contender = await run_write_race(db_engine, first, second)
    assert isinstance(result, Lesson)
    if move_first:
        assert isinstance(contender, LessonNotEditableError)
        assert contender.current_status == LessonStatus.RESCHEDULED
        assert result.instructor_id == original.instructor_id
    else:
        assert isinstance(contender, Lesson)
        assert contender.instructor_id == instructor


@pytest.mark.parametrize("action", ["cancel", "reschedule"])
@pytest.mark.parametrize("sweep_first", [False, True])
async def test_sweeper_races_with_cancel_or_reschedule(
    db_engine: AsyncEngine,
    racing_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    action: str,
    sweep_first: bool,
) -> None:
    original, _ = racing_lessons
    await _confirm_only_due_lesson(db_engine, original, clock)
    target = LessonStatus.CANCELLED if action == "cancel" else LessonStatus.RESCHEDULED

    async def sweep(service: LessonService) -> int:
        return await service.start_due_lessons(clock=clock)

    async def transition(service: LessonService) -> Lesson:
        if action == "cancel":
            return await service.cancel(original.id, reason=None, clock=clock)
        successor, _ = await service.reschedule(
            original.id, _NEW_INTERVAL, people=FakePeople(delay=0), clock=clock
        )
        return successor

    if sweep_first:
        processed, error = await run_write_race(db_engine, sweep, transition)
        assert processed == 1
        _assert_transition_rejected(error, LessonStatus.IN_PROGRESS, target)
        expected, successors = LessonStatus.IN_PROGRESS, []
    else:
        lesson, processed = await run_write_race(db_engine, transition, sweep)
        assert isinstance(lesson, Lesson)
        assert processed == 0
        expected, successors = target, [lesson.id] if action == "reschedule" else []

    assert (await _read(db_engine, original.id)).status == expected
    assert await _successors(db_engine, original.id) == successors


async def test_concurrent_sweepers_count_the_same_lesson_once(
    db_engine: AsyncEngine,
    racing_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
) -> None:
    original, _ = racing_lessons
    await _confirm_only_due_lesson(db_engine, original, clock)

    async def sweep(service: LessonService) -> int:
        return await service.start_due_lessons(clock=clock)

    assert await run_write_race(db_engine, sweep, sweep) == (1, 0)
    assert (await _read(db_engine, original.id)).status == LessonStatus.IN_PROGRESS
