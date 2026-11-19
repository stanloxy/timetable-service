"""Типизированные ответы внешнего сервиса people-stub."""

from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, model_validator


def _known_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Ожидается часовой пояс IANA") from exc
    return value


type IanaTimezone = Annotated[str, AfterValidator(_known_timezone)]


class Instructor(BaseModel):
    id: UUID
    full_name: str
    max_hours_per_day: float = Field(gt=0, allow_inf_nan=False)
    timezone: IanaTimezone


class AvailabilityWindow(BaseModel):
    weekday: int = Field(ge=1, le=7)
    starts_at: str = Field(alias="from", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    ends_at: str = Field(alias="to", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("Окончание окна должно быть позже начала")
        return self


class Availability(BaseModel):
    instructor_id: UUID
    timezone: IanaTimezone
    windows: list[AvailabilityWindow]


class Classroom(BaseModel):
    id: UUID
    name: str
    capacity: int = Field(ge=1)
    online_capable: bool
