from typing import Literal
from uuid import UUID

type ResourceKind = Literal["group", "lesson"]


class ServiceError(Exception):
    """Ожидаемая ошибка предметного сценария."""


class ResourceNotFoundError(ServiceError):
    def __init__(self, resource: ResourceKind, resource_id: UUID) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} not found: {resource_id}")


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
