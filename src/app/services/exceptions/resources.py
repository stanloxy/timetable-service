from typing import Literal
from uuid import UUID

from app.services.exceptions.base import ServiceError

type ResourceKind = Literal["group", "lesson"]


class ResourceNotFoundError(ServiceError):
    def __init__(self, resource: ResourceKind, resource_id: UUID) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} not found: {resource_id}")
