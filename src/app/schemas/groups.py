from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    size: int = Field(ge=1)
