import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.clock import AdjustableClock
from app.db.models import Group, Lesson
from app.enums.lessons import LessonFormat
from app.services.exceptions import LessonConflictError
from app.services.lesson_rules import LessonCandidate
from app.services.lessons import LessonService
from tests.integration.db.helpers import wait_for_database_lock
from tests.unit.test_lesson_reference_data import FakePeople


class AbortCommit(RuntimeError):
    """Остановить первую транзакцию после вставки, до commit."""


@pytest.mark.parametrize(
    ("shared_resource", "abort"),
    [("instructor", False), ("classroom", False), ("group", False), ("instructor", True)],
)
async def test_create_waits_then_rechecks_schedule(
    db_engine: AsyncEngine, shared_resource: str, abort: bool
) -> None:
    start = datetime(2026, 12, 14, 5, tzinfo=UTC)
    first = LessonCandidate(
        uuid4(), uuid4(), uuid4(), LessonFormat.IN_PERSON, start, start + timedelta(hours=1)
    )
    second = replace(
        first,
        group_id=first.group_id if shared_resource == "group" else uuid4(),
        instructor_id=first.instructor_id if shared_resource == "instructor" else uuid4(),
        classroom_id=first.classroom_id if shared_resource == "classroom" else uuid4(),
        starts_at=start + timedelta(minutes=30),
        ends_at=start + timedelta(minutes=90),
    )
    groups = {first.group_id, second.group_id}
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    inserted = asyncio.Event()
    release = asyncio.Event()
    clock = AdjustableClock()
    clock.freeze(start)

    class PausedCommitSession(AsyncSession):
        async def commit(self) -> None:
            await self.flush()
            inserted.set()
            await release.wait()
            if abort:
                raise AbortCommit
            await super().commit()

    try:
        async with sessions.begin() as setup:
            setup.add_all(Group(id=group_id, name="Группа", size=10) for group_id in groups)

        async with db_engine.connect() as first_conn, db_engine.connect() as second_conn:
            first_pid = await first_conn.scalar(text("SELECT pg_backend_pid()"))
            second_pid = await second_conn.scalar(text("SELECT pg_backend_pid()"))
            await first_conn.commit()
            await second_conn.commit()
            assert isinstance(first_pid, int)
            assert isinstance(second_pid, int)
            assert second_pid != first_pid
            writer = LessonService(
                async_sessionmaker[AsyncSession](
                    first_conn, class_=PausedCommitSession, expire_on_commit=False
                )
            )
            contender = LessonService(async_sessionmaker(second_conn, expire_on_commit=False))

            writer_task = asyncio.create_task(
                writer.create(first, people=FakePeople(delay=0), clock=clock)
            )
            contender_task = None
            try:
                await asyncio.wait_for(inserted.wait(), timeout=5)
                contender_task = asyncio.create_task(
                    contender.create(second, people=FakePeople(delay=0), clock=clock)
                )
                await wait_for_database_lock(db_engine, second_pid, first_pid)
                release.set()

                if abort:
                    with pytest.raises(AbortCommit):
                        await asyncio.wait_for(writer_task, timeout=5)
                    saved, _ = await asyncio.wait_for(contender_task, timeout=5)
                    assert saved.starts_at == second.starts_at
                else:
                    saved, _ = await asyncio.wait_for(writer_task, timeout=5)
                    with pytest.raises(LessonConflictError) as error:
                        await asyncio.wait_for(contender_task, timeout=5)
                    assert error.value.violation.code == "SCHEDULE_CONFLICT"
                    assert error.value.violation.details == {
                        "conflicts": [
                            {
                                "resource": shared_resource,
                                "lesson_id": str(saved.id),
                                "overlap": {
                                    "starts_at": "2026-12-14T05:30:00Z",
                                    "ends_at": "2026-12-14T06:00:00Z",
                                },
                            }
                        ]
                    }
            finally:
                for task in (writer_task, contender_task):
                    if task is not None:
                        if not task.done():
                            task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

        async with sessions() as verification:
            rows = await verification.scalars(select(Lesson.id).where(Lesson.group_id.in_(groups)))
            assert list(rows) == [saved.id]
    finally:
        async with sessions.begin() as cleanup:
            await cleanup.execute(delete(Lesson).where(Lesson.group_id.in_(groups)))
            await cleanup.execute(delete(Group).where(Group.id.in_(groups)))
