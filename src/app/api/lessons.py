from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import UUID4, BeforeValidator

from app.api.responses import error_responses
from app.context import get_context
from app.db.lesson_filters import LessonFilters
from app.db.models import Lesson
from app.errors import ApiError
from app.schemas.errors import ErrorBody
from app.schemas.lessons import (
    LessonCancel,
    LessonCreate,
    LessonListQuery,
    LessonPage,
    LessonPatch,
    LessonReschedule,
    LessonResponse,
    LessonValidationResult,
    LessonWithWarnings,
    require_patch_fields,
)
from app.services.lesson_results import LessonWarning
from app.services.lesson_rules import LessonCandidate
from app.services.lessons import LessonService

router = APIRouter(prefix="/lessons", tags=["lessons"])


def _with_warnings(lesson: Lesson, warnings: list[LessonWarning]) -> LessonWithWarnings:
    return LessonWithWarnings(
        lesson=LessonResponse.model_validate(lesson),
        warnings=[
            ErrorBody(code=warning.code, message=warning.message, details=warning.details)
            for warning in warnings
        ],
    )


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
    return _with_warnings(lesson, warnings)


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


@router.get("", response_model=LessonPage, responses=error_responses(422))
async def list_lessons(query: Annotated[LessonListQuery, Query()], request: Request) -> LessonPage:
    context = get_context(request)
    filters = LessonFilters(
        group_id=query.group_id,
        instructor_id=query.instructor_id,
        classroom_id=query.classroom_id,
        status=query.status,
        starts_from=query.starts_from,
        starts_before=query.starts_before,
    )
    items, total = await LessonService(context.session_factory).list_page(
        filters, limit=query.limit, offset=query.offset
    )
    return LessonPage(items=[LessonResponse.model_validate(item) for item in items], total=total)


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


@router.patch(
    "/{lesson_id}",
    response_model=LessonWithWarnings,
    responses=error_responses(400, 404, 409, 422, 502, 504),
)
async def edit_lesson(
    lesson_id: UUID4,
    body: Annotated[LessonPatch, BeforeValidator(require_patch_fields), Body()],
    request: Request,
) -> LessonWithWarnings:
    context = get_context(request)
    lesson, warnings = await LessonService(context.session_factory).edit(
        lesson_id, body, people=context.people_client, clock=context.clock
    )
    return _with_warnings(lesson, warnings)


async def _reject_json_null(request: Request) -> None:
    # FastAPI передаёт JSON null в проверку тела как его отсутствие.
    if (await request.body()).strip() == b"null":
        raise ApiError(
            400,
            "BAD_REQUEST",
            "Невалидный запрос",
            {"errors": [{"field": "body", "type": "dict_type"}]},
        )


@router.post(
    "/{lesson_id}/confirm",
    response_model=LessonResponse,
    responses=error_responses(404, 409),
)
async def confirm_lesson(lesson_id: UUID4, request: Request) -> LessonResponse:
    context = get_context(request)
    lesson = await LessonService(context.session_factory).confirm(lesson_id, clock=context.clock)
    return LessonResponse.model_validate(lesson)


@router.post(
    "/{lesson_id}/cancel",
    response_model=LessonResponse,
    responses=error_responses(400, 404, 409, 422),
    dependencies=[Depends(_reject_json_null)],
)
async def cancel_lesson(
    lesson_id: UUID4, request: Request, body: LessonCancel | None = None
) -> LessonResponse:
    context = get_context(request)
    lesson = await LessonService(context.session_factory).cancel(
        lesson_id, reason=body.reason if body is not None else None, clock=context.clock
    )
    return LessonResponse.model_validate(lesson)


@router.post(
    "/{lesson_id}/reschedule",
    status_code=201,
    response_model=LessonWithWarnings,
    responses=error_responses(400, 404, 409, 422, 502, 504),
    dependencies=[Depends(_reject_json_null)],
)
async def reschedule_lesson(
    lesson_id: UUID4, body: Annotated[LessonReschedule, Body()], request: Request
) -> LessonWithWarnings:
    context = get_context(request)
    lesson, warnings = await LessonService(context.session_factory).reschedule(
        lesson_id, body, people=context.people_client, clock=context.clock
    )
    return _with_warnings(lesson, warnings)


@router.post(
    "/{lesson_id}/complete",
    response_model=LessonResponse,
    responses=error_responses(404, 409),
)
async def complete_lesson(lesson_id: UUID4, request: Request) -> LessonResponse:
    context = get_context(request)
    lesson = await LessonService(context.session_factory).complete(lesson_id, clock=context.clock)
    return LessonResponse.model_validate(lesson)
