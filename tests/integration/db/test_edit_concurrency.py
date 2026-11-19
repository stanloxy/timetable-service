import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.clock import AdjustableClock
from app.db.models import Group, Lesson
from app.enums.lessons import LessonFormat
from app.services.exceptions.lessons import LessonConflictError, LessonValidationError
from app.services.lesson_results import LessonWarning
from app.services.lesson_rules import LessonCandidate
from app.services.lessons import LessonChanges, LessonService
from tests.integration.db.test_concurrency import wait_for_database_lock
from tests.unit.test_lesson_reference_data import FakePeople

_START = datetime(2026, 12, 14, 5, tzinfo=UTC)
Write = Callable[[LessonService], Awaitable[tuple[Lesson, list[LessonWarning]]]]


class AbortEditCommit(RuntimeError):
    """Прервать PATCH после отправки UPDATE и до commit."""


@pytest.fixture
def clock() -> AdjustableClock:
    result = AdjustableClock()
    result.freeze(_START)
    return result


@pytest.fixture
async def committed_lessons(
    db_engine: AsyncEngine, clock: AdjustableClock
) -> AsyncIterator[tuple[Lesson, Lesson]]:
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    groups = [uuid4(), uuid4()]
    candidate = LessonCandidate(
        groups[0], uuid4(), None, LessonFormat.ONLINE, _START, _START + timedelta(hours=1)
    )
    service = LessonService(sessions)
    people = FakePeople(delay=0)
    try:
        async with sessions.begin() as session:
            session.add_all(Group(id=group_id, name="Группа", size=10) for group_id in groups)

        first, _ = await service.create(candidate, people=people, clock=clock)
        second, _ = await service.create(
            replace(
                candidate,
                group_id=groups[1],
                instructor_id=uuid4(),
                starts_at=_START + timedelta(hours=2),
                ends_at=_START + timedelta(hours=3),
            ),
            people=people,
            clock=clock,
        )
        yield first, second
    finally:
        async with sessions.begin() as session:
            await session.execute(delete(Lesson).where(Lesson.group_id.in_(groups)))
            await session.execute(delete(Group).where(Group.id.in_(groups)))


async def _race(
    engine: AsyncEngine, first: Write, second: Write, *, abort: bool = False
) -> tuple[Lesson | BaseException, Lesson | BaseException]:
    flushed = asyncio.Event()
    release = asyncio.Event()

    class PausedCommitSession(AsyncSession):
        async def commit(self) -> None:
            await self.flush()
            flushed.set()
            await release.wait()
            if abort:
                raise AbortEditCommit
            await super().commit()

    async def write(operation: Write, service: LessonService) -> Lesson:
        saved, _ = await operation(service)
        return saved

    async with engine.connect() as first_conn, engine.connect() as second_conn:
        first_pid = await first_conn.scalar(text("SELECT pg_backend_pid()"))
        second_pid = await second_conn.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(first_pid, int)
        assert isinstance(second_pid, int)
        assert first_pid != second_pid
        await first_conn.commit()
        await second_conn.commit()
        first_service = LessonService(
            async_sessionmaker[AsyncSession](
                first_conn, class_=PausedCommitSession, expire_on_commit=False
            )
        )
        second_service = LessonService(async_sessionmaker(second_conn, expire_on_commit=False))

        winner = asyncio.create_task(write(first, first_service))
        contender = None
        try:
            await asyncio.wait_for(flushed.wait(), timeout=5)
            contender = asyncio.create_task(write(second, second_service))
            await wait_for_database_lock(engine, second_pid, first_pid)
            release.set()
            first_result, second_result = await asyncio.wait_for(
                asyncio.gather(winner, contender, return_exceptions=True), timeout=5
            )
            return first_result, second_result
        finally:
            for task in (winner, contender):
                if task is not None:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


async def _read(engine: AsyncEngine, lesson_id: UUID) -> Lesson:
    return await LessonService(async_sessionmaker(engine, expire_on_commit=False)).get_by_id(
        lesson_id
    )


def _new_at_same_time(edited: Lesson, other: Lesson, instructor_id: UUID) -> LessonCandidate:
    return LessonCandidate(
        other.group_id, instructor_id, None, LessonFormat.ONLINE, edited.starts_at, edited.ends_at
    )


def _assert_instructor_conflict(result: Lesson | BaseException, winner: Lesson) -> None:
    assert isinstance(result, LessonConflictError)
    assert result.violation.code == "SCHEDULE_CONFLICT"
    assert result.violation.details == {
        "conflicts": [
            {
                "resource": "instructor",
                "lesson_id": str(winner.id),
                "overlap": {"starts_at": "2026-12-14T05:00:00Z", "ends_at": "2026-12-14T06:00:00Z"},
            }
        ]
    }


@pytest.mark.parametrize("post_first", [True, False])
async def test_create_and_edit_serialize_on_the_new_resource(
    db_engine: AsyncEngine,
    committed_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    post_first: bool,
) -> None:
    edited, other = committed_lessons
    target = uuid4()
    people = FakePeople(delay=0)

    async def create(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.create(
            _new_at_same_time(edited, other, target), people=people, clock=clock
        )

    async def edit(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.edit(edited.id, {"instructor_id": target}, people=people, clock=clock)

    first, second = (create, edit) if post_first else (edit, create)
    winner, rejected = await _race(db_engine, first, second)
    assert isinstance(winner, Lesson)
    assert winner.instructor_id == target
    _assert_instructor_conflict(rejected, winner)
    saved = await _read(db_engine, edited.id)
    assert saved.instructor_id == (edited.instructor_id if post_first else target)

    async with AsyncSession(db_engine) as check:
        at_target = await check.scalars(select(Lesson.id).where(Lesson.instructor_id == target))
        assert list(at_target) == [winner.id]


@pytest.mark.parametrize("abort", [False, True])
async def test_create_waits_for_the_released_resource(
    db_engine: AsyncEngine,
    committed_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    abort: bool,
) -> None:
    edited, other = committed_lessons
    target = uuid4()
    people = FakePeople(delay=0)

    async def edit(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.edit(edited.id, {"instructor_id": target}, people=people, clock=clock)

    async def create(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.create(
            _new_at_same_time(edited, other, edited.instructor_id), people=people, clock=clock
        )

    edit_result, create_result = await _race(db_engine, edit, create, abort=abort)
    saved = await _read(db_engine, edited.id)
    if abort:
        assert isinstance(edit_result, AbortEditCommit)
        _assert_instructor_conflict(create_result, edited)
        assert saved.instructor_id == edited.instructor_id
    else:
        assert isinstance(edit_result, Lesson)
        assert isinstance(create_result, Lesson)
        assert saved.instructor_id == target
        assert create_result.instructor_id == edited.instructor_id


@pytest.mark.parametrize("second_edit", ["different_field", "same_field", "invalid"])
async def test_two_edits_apply_to_the_latest_version(
    db_engine: AsyncEngine,
    committed_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
    second_edit: str,
) -> None:
    edited, _ = committed_lessons
    first_end = _START + timedelta(minutes=90)
    last_end = _START + timedelta(minutes=45)
    new_instructor = uuid4()
    changes: dict[str, LessonChanges] = {
        "different_field": {"instructor_id": new_instructor},
        "same_field": {"ends_at": last_end},
        "invalid": {"ends_at": _START},
    }
    people = FakePeople(delay=0)

    async def edit_first(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.edit(edited.id, {"ends_at": first_end}, people=people, clock=clock)

    async def edit_second(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.edit(edited.id, changes[second_edit], people=people, clock=clock)

    first, second = await _race(db_engine, edit_first, edit_second)
    assert isinstance(first, Lesson)
    assert first.ends_at == first_end
    if second_edit == "invalid":
        assert isinstance(second, LessonValidationError)
    else:
        assert isinstance(second, Lesson)

    saved = await _read(db_engine, edited.id)
    assert saved.instructor_id == (
        new_instructor if second_edit == "different_field" else edited.instructor_id
    )
    assert saved.ends_at == (last_end if second_edit == "same_field" else first_end)


async def test_two_lessons_exchange_instructors_in_disjoint_intervals(
    db_engine: AsyncEngine,
    committed_lessons: tuple[Lesson, Lesson],
    clock: AdjustableClock,
) -> None:
    first, second = committed_lessons
    people = FakePeople(delay=0)

    async def edit_first(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.edit(
            first.id, {"instructor_id": second.instructor_id}, people=people, clock=clock
        )

    async def edit_second(service: LessonService) -> tuple[Lesson, list[LessonWarning]]:
        return await service.edit(
            second.id, {"instructor_id": first.instructor_id}, people=people, clock=clock
        )

    first_result, second_result = await _race(db_engine, edit_first, edit_second)
    assert isinstance(first_result, Lesson)
    assert isinstance(second_result, Lesson)
    assert (await _read(db_engine, first.id)).instructor_id == second.instructor_id
    assert (await _read(db_engine, second.id)).instructor_id == first.instructor_id
