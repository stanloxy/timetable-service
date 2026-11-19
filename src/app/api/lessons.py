from uuid import UUID

from fastapi import APIRouter, Request

from app.api.responses import error_responses
from app.context import get_context
from app.schemas.errors import ErrorBody
from app.schemas.lessons import (
    LessonCreate,
    LessonResponse,
    LessonValidationResult,
    LessonWithWarnings,
)
from app.services.lesson_rules import LessonCandidate
from app.services.lessons import LessonService

router = APIRouter(prefix="/lessons", tags=["lessons"])


def _candidate(body: LessonCreate) -> LessonCandidate:
    return LessonCandidate(
        group_id=body.group_id,
        instructor_id=body.instructor_id,
        classroom_id=body.classroom_id,
        format=body.format,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )


@router.post(
    "",
    status_code=201,
    response_model=LessonWithWarnings,
    responses=error_responses(400, 409, 422, 502, 504),
)
async def create_lesson(body: LessonCreate, request: Request) -> LessonWithWarnings:
    context = get_context(request)
    lesson, warnings = await LessonService(context.session_factory).create(
        _candidate(body), people=context.people_client, clock=context.clock
    )
    return LessonWithWarnings(
        lesson=LessonResponse.model_validate(lesson),
        warnings=[
            ErrorBody(code=warning.code, message=warning.message, details=warning.details)
            for warning in warnings
        ],
    )


@router.post(
    "/validate",
    response_model=LessonValidationResult,
    responses=error_responses(400, 422, 502, 504),
)
async def validate_lesson(body: LessonCreate, request: Request) -> LessonValidationResult:
    context = get_context(request)
    validation = await LessonService(context.session_factory).validate(
        _candidate(body), people=context.people_client
    )
    violation = validation.violation
    violations = []
    if violation is not None:
        violations.append(
            ErrorBody(code=violation.code, message=violation.message, details=violation.details)
        )
    warnings = [
        ErrorBody(code=warning.code, message=warning.message, details=warning.details)
        for warning in validation.warnings
    ]
    return LessonValidationResult(
        ok=violation is None,
        violations=violations,
        warnings=warnings,
    )


@router.get(
    "/{lesson_id}",
    response_model=LessonResponse,
    responses=error_responses(404),
)
async def get_lesson(lesson_id: UUID, request: Request) -> LessonResponse:
    context = get_context(request)
    service = LessonService(context.session_factory)
    lesson = await service.get_by_id(lesson_id)
    return LessonResponse.model_validate(lesson)
