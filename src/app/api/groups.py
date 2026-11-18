from uuid import UUID

from fastapi import APIRouter, Request

from app.context import get_context
from app.schemas.errors import ErrorResponse
from app.schemas.groups import GroupResponse
from app.services.groups import GroupService

router = APIRouter(prefix="/groups", tags=["groups"])


@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_group(group_id: UUID, request: Request) -> GroupResponse:
    context = get_context(request)
    service = GroupService(context.session_factory)
    group = await service.get_by_id(group_id)
    return GroupResponse.model_validate(group)
