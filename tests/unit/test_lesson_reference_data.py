import asyncio
from time import perf_counter
from uuid import UUID

import pytest

from app.clients.people import PeopleTimeoutError, PeopleUnavailableError
from app.clients.people_models import Availability, Classroom, Instructor
from app.enums.lessons import LessonFormat
from app.services.exceptions import (
    InstructorNotFoundError,
    ServiceError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from app.services.lesson_reference_data import LessonReferenceData, collect_lesson_reference_data

INSTRUCTOR_ID = UUID("1b000000-0000-4000-8000-000000000001")
CLASSROOM_ID = UUID("2c000000-0000-4000-8000-000000000001")


class FakePeople:
    def __init__(self, delay: float | None) -> None:
        self.delay = delay
        self.delays: dict[str, float] = {}
        self.failures: dict[str, Exception | None] = {}
        self.calls: list[str] = []
        self.finished: list[str] = []
        self.active = 0
        self.peak = 0
        self.all_started = asyncio.Event()

    async def _read[Result](self, name: str, result: Result) -> Result | None:
        self.calls.append(name)
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == 3:
            self.all_started.set()
        try:
            delay = self.delays.get(name, self.delay)
            if delay is None:
                await asyncio.Event().wait()
            else:
                await asyncio.sleep(delay)
            if name in self.failures:
                error = self.failures[name]
                if error is not None:
                    raise error
                return None
            return result
        finally:
            self.active -= 1
            self.finished.append(name)

    async def get_instructor(self, instructor_id: UUID) -> Instructor | None:
        return await self._read(
            "profile",
            Instructor(
                id=instructor_id,
                full_name="Анна Королёва",
                max_hours_per_day=6,
                timezone="Asia/Yekaterinburg",
            ),
        )

    async def get_availability(self, instructor_id: UUID) -> Availability | None:
        return await self._read(
            "availability",
            Availability(instructor_id=instructor_id, timezone="Asia/Yekaterinburg", windows=[]),
        )

    async def get_classroom(self, classroom_id: UUID) -> Classroom | None:
        return await self._read(
            "classroom",
            Classroom(id=classroom_id, name="Ауд. 101", capacity=30, online_capable=True),
        )


async def test_async_case() -> None:
    sequential = FakePeople(delay=0.3)
    started = perf_counter()
    instructor = await sequential.get_instructor(INSTRUCTOR_ID)
    availability = await sequential.get_availability(INSTRUCTOR_ID)
    classroom = await sequential.get_classroom(CLASSROOM_ID)
    sequential_ms = (perf_counter() - started) * 1000

    concurrent = FakePeople(delay=0.3)
    started = perf_counter()
    result = await collect_lesson_reference_data(
        concurrent,
        lesson_format=LessonFormat.IN_PERSON,
        instructor_id=INSTRUCTOR_ID,
        classroom_id=CLASSROOM_ID,
    )
    concurrent_ms = (perf_counter() - started) * 1000

    assert instructor is not None
    assert availability is not None
    assert classroom is not None
    assert result == LessonReferenceData(instructor, availability, classroom)
    assert sorted(concurrent.calls) == sorted(sequential.calls)
    assert sequential.peak == 1
    assert concurrent.peak == 3
    # Сравниваем два замера с запасом на задержки планировщика.
    assert concurrent_ms < sequential_ms * 0.75
    print(f"Sequential: {sequential_ms:.1f} ms; concurrent: {concurrent_ms:.1f} ms")


async def test_online_only_fetches_instructor_data() -> None:
    people = FakePeople(delay=0)
    result = await collect_lesson_reference_data(
        people,
        lesson_format=LessonFormat.ONLINE,
        instructor_id=INSTRUCTOR_ID,
        classroom_id=None,
    )

    assert sorted(people.calls) == ["availability", "profile"]
    assert people.peak == 2
    assert result.instructor.id == result.availability.instructor_id == INSTRUCTOR_ID
    assert result.classroom is None


@pytest.mark.parametrize("last_to_finish", ["classroom", "availability"])
@pytest.mark.parametrize(
    ("classroom_failure", "availability_failure", "expected"),
    [
        (None, None, InstructorNotFoundError),
        (None, PeopleUnavailableError("maintenance"), UpstreamUnavailableError),
        (PeopleTimeoutError(50), PeopleUnavailableError("maintenance"), UpstreamTimeoutError),
    ],
)
async def test_failures_have_fixed_priority(
    last_to_finish: str,
    classroom_failure: Exception | None,
    availability_failure: Exception | None,
    expected: type[ServiceError],
) -> None:
    people = FakePeople(delay=0)
    people.delays[last_to_finish] = 0.01
    people.failures = {"classroom": classroom_failure, "availability": availability_failure}

    with pytest.raises(expected):
        await collect_lesson_reference_data(
            people,
            lesson_format=LessonFormat.IN_PERSON,
            instructor_id=INSTRUCTOR_ID,
            classroom_id=CLASSROOM_ID,
        )

    assert people.finished[-1] == last_to_finish
    assert people.active == 0


async def test_cancelling_collection_finishes_in_flight_calls() -> None:
    people = FakePeople(delay=None)
    collection = asyncio.create_task(
        collect_lesson_reference_data(
            people,
            lesson_format=LessonFormat.IN_PERSON,
            instructor_id=INSTRUCTOR_ID,
            classroom_id=CLASSROOM_ID,
        )
    )
    try:
        async with asyncio.timeout(2):
            await people.all_started.wait()
    finally:
        collection.cancel()
        with pytest.raises(asyncio.CancelledError):
            await collection

    assert sorted(people.finished) == ["availability", "classroom", "profile"]
    assert people.active == 0
