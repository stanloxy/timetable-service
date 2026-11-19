import re
from datetime import datetime
from uuid import UUID

from pydantic import UUID4, AwareDatetime, BaseModel, ConfigDict, field_serializer, field_validator
from pydantic_core import PydanticCustomError

from app.clock import to_iso_z
from app.enums.lessons import LessonFormat, LessonStatus
from app.schemas.errors import ErrorBody

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[Tt ]|$)")


class LessonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: UUID4
    instructor_id: UUID4
    classroom_id: UUID4 | None = None
    format: LessonFormat
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @field_validator("starts_at", "ends_at", mode="before")
    @classmethod
    def require_iso_datetime(cls, value: object) -> object:
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            raise PydanticCustomError("datetime_type", "Ожидается строка даты и времени")
        if not _ISO_DATE.match(value):
            raise ValueError("Ожидается ISO 8601 со смещением")
        return value

    @field_validator("format", mode="before")
    @classmethod
    def require_string_format(cls, value: object) -> object:
        if not isinstance(value, str):
            raise PydanticCustomError("string_type", "Ожидается строка формата занятия")
        return value


class LessonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_id: UUID
    instructor_id: UUID
    classroom_id: UUID | None
    format: LessonFormat
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    status: LessonStatus
    rescheduled_from_id: UUID | None
    cancel_reason: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_serializer(
        "starts_at",
        "ends_at",
        "created_at",
        "updated_at",
        when_used="json",
    )
    def serialize_datetime(self, value: datetime) -> str:
        return to_iso_z(value, preserve_fraction=True)


class LessonWithWarnings(BaseModel):
    lesson: LessonResponse
    warnings: list[ErrorBody]


class LessonValidationResult(BaseModel):
    ok: bool
    violations: list[ErrorBody]
    warnings: list[ErrorBody]
