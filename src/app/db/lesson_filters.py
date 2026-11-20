from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.enums.lessons import LessonStatus


@dataclass(frozen=True)
class LessonFilters:
    group_id: UUID | None
    instructor_id: UUID | None
    classroom_id: UUID | None
    status: LessonStatus | None
    starts_from: datetime | None
    starts_before: datetime | None
