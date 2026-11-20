from datetime import datetime
from uuid import UUID

from app.enums.lessons import LessonStatus
from app.services.exceptions.base import ServiceError
from app.services.lesson_results import LessonViolation


class GroupNotFoundError(ServiceError):
    def __init__(self, group_id: UUID) -> None:
        self.group_id = group_id
        super().__init__(f"Group not found: {group_id}")


class LessonValidationError(ServiceError):
    def __init__(self, field: str, message: str) -> None:
        self.fields = {field: message}
        super().__init__(message)


class ClassroomRequiredError(ServiceError):
    """Очное занятие требует аудиторию."""


class LessonNotEditableError(ServiceError):
    def __init__(self, current_status: LessonStatus) -> None:
        self.current_status = current_status
        super().__init__(f"Lesson in status {current_status} cannot be edited")


class LessonTransitionForbiddenError(ServiceError):
    def __init__(self, current_status: LessonStatus, target_status: LessonStatus) -> None:
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(f"Lesson transition from {current_status} to {target_status} is forbidden")


class LessonNotFinishedError(ServiceError):
    def __init__(self, ends_at: datetime, now: datetime) -> None:
        self.ends_at = ends_at
        self.now = now
        super().__init__("Lesson has not finished yet")


class LessonConflictError(ServiceError):
    def __init__(self, violation: LessonViolation) -> None:
        self.violation = violation
        super().__init__(violation.message)
