from uuid import UUID

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


class LessonConflictError(ServiceError):
    def __init__(self, violation: LessonViolation) -> None:
        self.violation = violation
        super().__init__(violation.message)
