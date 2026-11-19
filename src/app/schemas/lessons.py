import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    UUID4,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_serializer,
    with_config,
)
from pydantic_core import PydanticCustomError
from typing_extensions import TypedDict

from app.clock import to_iso_z
from app.enums.lessons import LessonFormat, LessonStatus
from app.schemas.errors import ErrorBody

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[Tt ]|$)")


def _require_iso_datetime(value: object) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise PydanticCustomError("datetime_type", "Ожидается строка даты и времени")
    if not _ISO_DATE.match(value):
        raise ValueError("Ожидается ISO 8601 со смещением")
    return value


def _require_string_format(value: object) -> str:
    if not isinstance(value, str):
        raise PydanticCustomError("string_type", "Ожидается строка формата занятия")
    return value


IsoDateTime = Annotated[AwareDatetime, BeforeValidator(_require_iso_datetime)]
InputLessonFormat = Annotated[LessonFormat, BeforeValidator(_require_string_format)]


class LessonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: UUID4
    instructor_id: UUID4
    classroom_id: UUID4 | None = None
    format: InputLessonFormat
    starts_at: IsoDateTime
    ends_at: IsoDateTime


@with_config(ConfigDict(extra="forbid", json_schema_extra={"minProperties": 1}))
class LessonPatch(TypedDict, total=False):
    instructor_id: UUID4
    classroom_id: UUID4 | None
    format: InputLessonFormat
    starts_at: IsoDateTime
    ends_at: IsoDateTime


def require_patch_fields(value: object) -> object:
    if isinstance(value, dict) and not value:
        raise ValueError("Передайте хотя бы одно поле занятия")
    return value


def _query_integer(value: object) -> object:
    if isinstance(value, str) and not re.fullmatch(r"[+-]?[0-9]+", value):
        raise ValueError("Ожидается целое число")
    return value


QueryInteger = Annotated[int, BeforeValidator(_query_integer)]


class LessonListQuery(BaseModel):
    group_id: UUID4 | None = None
    instructor_id: UUID4 | None = None
    classroom_id: UUID4 | None = None
    status: LessonStatus | None = None
    starts_from: IsoDateTime | None = Field(default=None, alias="from")
    starts_before: IsoDateTime | None = Field(default=None, alias="to")
    limit: QueryInteger = Field(default=50, ge=1, le=200)
    offset: QueryInteger = Field(default=0, ge=0)


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


class LessonPage(BaseModel):
    items: list[LessonResponse]
    total: int


class LessonValidationResult(BaseModel):
    ok: bool
    violations: list[ErrorBody]
    warnings: list[ErrorBody]
