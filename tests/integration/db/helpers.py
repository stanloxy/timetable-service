import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import Lesson
from app.enums.lessons import LessonStatus
from app.services.lessons import LessonService


def make_successor(original: Lesson, successor_id: UUID) -> Lesson:
    """Подготовить новое занятие со ссылкой на исходное."""
    return Lesson(
        id=successor_id,
        group_id=original.group_id,
        instructor_id=original.instructor_id,
        classroom_id=original.classroom_id,
        status=LessonStatus.PLANNED,
        format=original.format,
        starts_at=original.starts_at + timedelta(days=1),
        ends_at=original.ends_at + timedelta(days=1),
        rescheduled_from_id=original.id,
        cancel_reason=None,
        created_at=original.created_at,
        updated_at=original.updated_at,
    )


async def save_in_savepoint(
    session: AsyncSession,
    lesson: Lesson,
) -> None:
    async with session.begin_nested():
        session.add(lesson)
        await session.flush()


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


class AbortWriteCommit(RuntimeError):
    """Прервать запись между flush и commit."""


async def run_write_race[First, Second](
    engine: AsyncEngine,
    first: Callable[[LessonService], Awaitable[First]],
    second: Callable[[LessonService], Awaitable[Second]],
    *,
    abort: bool = False,
) -> tuple[First | BaseException, Second | BaseException]:
    """Pause the first transaction after flush until PostgreSQL confirms contention."""
    flushed = asyncio.Event()
    release = asyncio.Event()

    class PausedCommitSession(AsyncSession):
        async def commit(self) -> None:
            await self.flush()
            flushed.set()
            await release.wait()
            if abort:
                raise AbortWriteCommit
            await super().commit()

    async def invoke[Result](
        operation: Callable[[LessonService], Awaitable[Result]], service: LessonService
    ) -> Result:
        return await operation(service)

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

        winner = asyncio.create_task(invoke(first, first_service))
        contender = None
        try:
            await asyncio.wait_for(flushed.wait(), timeout=5)
            contender = asyncio.create_task(invoke(second, second_service))
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
