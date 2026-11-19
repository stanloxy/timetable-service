"""Типизированные ответы внешнего сервиса people-stub."""

from uuid import UUID

from pydantic import BaseModel, Field


class Instructor(BaseModel):
    id: UUID
    full_name: str
    max_hours_per_day: float = Field(gt=0, allow_inf_nan=False)
    timezone: str


class AvailabilityWindow(BaseModel):
    weekday: int = Field(ge=1, le=7)
    starts_at: str = Field(alias="from", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    ends_at: str = Field(alias="to", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class Availability(BaseModel):
    instructor_id: UUID
    timezone: str
    windows: list[AvailabilityWindow]


class Classroom(BaseModel):
    id: UUID
    name: str
    capacity: int = Field(ge=1)
    online_capable: bool
