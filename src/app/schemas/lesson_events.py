from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, computed_field, field_serializer

from app.clock import to_iso_z
from app.enums.lessons import LessonFormat, LessonStatus

type EventType = Literal["LessonConfirmed", "LessonCancelled", "LessonRescheduled"]

_KEY_PREFIX: dict[EventType, str] = {
    "LessonConfirmed": "lesson-confirmed",
    "LessonCancelled": "lesson-cancelled",
    "LessonRescheduled": "lesson-rescheduled",
}


def _serialize_lesson_time(value: datetime) -> str:
    return to_iso_z(value, preserve_fraction=True)


LessonTime = Annotated[datetime, PlainSerializer(_serialize_lesson_time, when_used="json")]


class LessonInterval(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    starts_at: LessonTime
    ends_at: LessonTime
    instructor_id: UUID
    classroom_id: UUID | None


class LessonEventPayload(BaseModel):
    lesson_id: UUID
    group_id: UUID
    instructor_id: UUID


class LessonConfirmedPayload(LessonEventPayload):
    classroom_id: UUID | None
    format: LessonFormat
    starts_at: LessonTime
    ends_at: LessonTime


class LessonCancelledPayload(LessonEventPayload):
    starts_at: LessonTime
    ends_at: LessonTime
    previous_status: LessonStatus
    reason: str | None


class LessonRescheduledPayload(LessonEventPayload):
    rescheduled_to_id: UUID
    previous: LessonInterval
    new: LessonInterval


class LessonEvent[Payload: LessonEventPayload](BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    occurred_at: datetime
    producer: Literal["timetable-service"] = "timetable-service"
    version: Literal[1] = 1
    payload: Payload

    @computed_field
    def idempotency_key(self) -> str:
        return f"{_KEY_PREFIX[self.event_type]}:{self.payload.lesson_id}"

    @field_serializer("occurred_at", when_used="json")
    def _serialize_occurred_at(self, value: datetime) -> str:
        return to_iso_z(value)


type PublishedLessonEvent = (
    LessonEvent[LessonConfirmedPayload]
    | LessonEvent[LessonCancelledPayload]
    | LessonEvent[LessonRescheduledPayload]
)
