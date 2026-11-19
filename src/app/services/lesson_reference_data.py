import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.clients.errors.people import PeopleTimeoutError, PeopleUnavailableError
from app.clients.people_models import Availability, Classroom, Instructor
from app.enums.lessons import LessonFormat
from app.services.exceptions.people import (
    ClassroomNotFoundError,
    InstructorNotFoundError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)


class PeopleReader(Protocol):
    async def get_instructor(self, instructor_id: UUID) -> Instructor | None: ...

    async def get_availability(self, instructor_id: UUID) -> Availability | None: ...

    async def get_classroom(self, classroom_id: UUID) -> Classroom | None: ...


@dataclass(frozen=True)
class LessonReferenceData:
    instructor: Instructor
    availability: Availability
    classroom: Classroom | None


async def collect_lesson_reference_data(
    people: PeopleReader,
    *,
    lesson_format: LessonFormat,
    instructor_id: UUID,
    classroom_id: UUID | None,
) -> LessonReferenceData:
    """Собрать данные занятия после проверки формата и идентификатора аудитории."""
    if lesson_format is LessonFormat.IN_PERSON and classroom_id is None:
        raise ValueError("An in-person lesson requires a classroom ID before collecting data")

    instructor_task = asyncio.create_task(people.get_instructor(instructor_id))
    availability_task = asyncio.create_task(people.get_availability(instructor_id))
    classroom_task = None
    if lesson_format is LessonFormat.IN_PERSON and classroom_id is not None:
        classroom_task = asyncio.create_task(people.get_classroom(classroom_id))

    tasks: list[asyncio.Task[object]] = [instructor_task, availability_task]
    if classroom_task is not None:
        tasks.append(classroom_task)

    # Ждём все вызовы в пределах их таймаутов, чтобы выбрать ошибку по фиксированному приоритету.
    # Отмена сборки передаётся всем незавершённым вызовам.
    await asyncio.gather(*tasks, return_exceptions=True)
    _raise_request_failure([task.exception() for task in tasks])

    instructor = instructor_task.result()
    availability = availability_task.result()
    if instructor is None or availability is None:
        raise InstructorNotFoundError(instructor_id)

    classroom = None
    if classroom_task is not None and classroom_id is not None:
        classroom = classroom_task.result()
        if classroom is None:
            raise ClassroomNotFoundError(classroom_id)

    return LessonReferenceData(instructor, availability, classroom)


def _raise_request_failure(errors: list[BaseException | None]) -> None:
    for error in errors:
        if error is not None and not isinstance(
            error, (PeopleTimeoutError, PeopleUnavailableError)
        ):
            raise error
    for error in errors:
        if isinstance(error, PeopleTimeoutError):
            raise UpstreamTimeoutError(error.timeout_ms) from error
    for error in errors:
        if isinstance(error, PeopleUnavailableError):
            raise UpstreamUnavailableError() from error
