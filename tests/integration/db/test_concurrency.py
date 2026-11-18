import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.models import Group, Lesson
from app.enums.lessons import LessonFormat, LessonStatus
from tests.integration.db.helpers import make_successor


async def wait_for_database_lock(
    engine: AsyncEngine,
    blocked_pid: int,
    blocker_pid: int,
) -> None:
    """Дождаться подтверждённой PostgreSQL блокировки."""
    async with engine.connect() as connection:
        async with asyncio.timeout(5):
            while True:
                blocked = await connection.scalar(
                    text("SELECT :blocker = ANY(pg_blocking_pids(:blocked))"),
                    {"blocker": blocker_pid, "blocked": blocked_pid},
                )
                if blocked:
                    return
                await asyncio.sleep(0.01)


async def test_concurrent_successors(
    db_engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    group_id = uuid4()
    original_id = uuid4()
    starts_at = datetime(2026, 12, 1, 5, tzinfo=UTC)

    original = Lesson(
        id=original_id,
        group_id=group_id,
        instructor_id=UUID("1b000000-0000-4000-8000-000000000001"),
        classroom_id=None,
        status=LessonStatus.RESCHEDULED,
        format=LessonFormat.ONLINE,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        rescheduled_from_id=None,
        cancel_reason=None,
        created_at=starts_at,
        updated_at=starts_at,
    )
    first = make_successor(original, uuid4())
    second = make_successor(original, uuid4())

    try:
        # Исходные данные должны быть видны обоим соединениям.
        async with sessions.begin() as setup:
            setup.add(Group(id=group_id, name="Конкурентный тест", size=12))
            await setup.flush()
            setup.add(original)

        async with sessions() as winner, sessions() as contender:
            winner_pid = await winner.scalar(text("SELECT pg_backend_pid()"))
            contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(winner_pid, int)
            assert isinstance(contender_pid, int)
            assert winner_pid != contender_pid

            winner.add(first)
            await winner.flush()

            async def insert_contender() -> None:
                # Даже при ошибке теста блокировка не будет бесконечной.
                await contender.execute(text("SET LOCAL statement_timeout = '10s'"))
                contender.add(second)
                await contender.commit()

            task = asyncio.create_task(insert_contender())
            try:
                await wait_for_database_lock(db_engine, contender_pid, winner_pid)
                await winner.commit()

                with pytest.raises(IntegrityError) as error:
                    await asyncio.wait_for(task, timeout=5)

                assert "uq_lessons_rescheduled_from_id" in str(error.value.orig)
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        async with sessions() as verification:
            successor_ids = await verification.scalars(
                select(Lesson.id).where(Lesson.rescheduled_from_id == original_id)
            )
            assert list(successor_ids) == [first.id]
    finally:
        # Здесь были реальные commit: внешний rollback фикстуры не поможет.
        # Удаляем только строки этого теста, определяемые случайным group_id.
        async with sessions.begin() as cleanup:
            await cleanup.execute(delete(Lesson).where(Lesson.group_id == group_id))
            await cleanup.execute(delete(Group).where(Group.id == group_id))
