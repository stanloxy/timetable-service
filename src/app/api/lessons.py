from uuid import UUID

from fastapi import APIRouter, Request

from app.context import get_context
from app.schemas.errors import ErrorResponse
from app.schemas.lessons import LessonResponse
from app.services.lessons import LessonService

router = APIRouter(prefix="/lessons", tags=["lessons"])


@router.get(
    "/{lesson_id}",
    response_model=LessonResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_lesson(lesson_id: UUID, request: Request) -> LessonResponse:
    context = get_context(request)
    service = LessonService(context.session_factory)
    lesson = await service.get_by_id(lesson_id)
    return LessonResponse.model_validate(lesson)
