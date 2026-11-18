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
