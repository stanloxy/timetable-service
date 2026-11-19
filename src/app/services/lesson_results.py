from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LessonWarning:
    code: Literal["WORKLOAD_SOFT_LIMIT", "INSTRUCTOR_UNAVAILABLE"]
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class LessonViolation:
    code: Literal["CLASSROOM_TOO_SMALL", "SCHEDULE_CONFLICT"]
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class LessonValidation:
    warnings: list[LessonWarning]
    violation: LessonViolation | None = None
