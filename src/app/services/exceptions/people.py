from uuid import UUID

from app.services.exceptions.base import ServiceError


class InstructorNotFoundError(ServiceError):
    def __init__(self, instructor_id: UUID) -> None:
        self.instructor_id = instructor_id
        super().__init__(f"Instructor not found: {instructor_id}")


class ClassroomNotFoundError(ServiceError):
    def __init__(self, classroom_id: UUID) -> None:
        self.classroom_id = classroom_id
        super().__init__(f"Classroom not found: {classroom_id}")


class UpstreamUnavailableError(ServiceError):
    """Соседний сервис не предоставил пригодный ответ."""


class UpstreamTimeoutError(ServiceError):
    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        super().__init__(f"Upstream request exceeded {timeout_ms} ms")
