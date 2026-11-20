from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors.responses import error_response
from app.clock import to_iso_z
from app.services.exceptions.lessons import (
    ClassroomRequiredError,
    GroupNotFoundError,
    LessonConflictError,
    LessonNotEditableError,
    LessonNotFinishedError,
    LessonTransitionForbiddenError,
    LessonValidationError,
)


def install_lesson_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GroupNotFoundError)
    async def _group_not_found(_: Request, exc: GroupNotFoundError) -> JSONResponse:
        return error_response(
            422, "GROUP_NOT_FOUND", "Группа не найдена", {"group_id": str(exc.group_id)}
        )

    @app.exception_handler(LessonValidationError)
    async def _lesson_validation(_: Request, exc: LessonValidationError) -> JSONResponse:
        return error_response(422, "VALIDATION_ERROR", "Невалидные данные", {"fields": exc.fields})

    @app.exception_handler(ClassroomRequiredError)
    async def _classroom_required(_: Request, __: ClassroomRequiredError) -> JSONResponse:
        return error_response(422, "CLASSROOM_REQUIRED", "Для очного занятия нужна аудитория")

    @app.exception_handler(LessonConflictError)
    async def _lesson_conflict(_: Request, exc: LessonConflictError) -> JSONResponse:
        violation = exc.violation
        return error_response(409, violation.code, violation.message, violation.details)

    @app.exception_handler(LessonNotEditableError)
    async def _lesson_not_editable(_: Request, exc: LessonNotEditableError) -> JSONResponse:
        return error_response(
            409,
            "LESSON_NOT_EDITABLE",
            "Изменять можно только занятие в статусе PLANNED",
            {"current_status": exc.current_status.value},
        )

    @app.exception_handler(LessonTransitionForbiddenError)
    async def _transition_forbidden(
        _: Request, exc: LessonTransitionForbiddenError
    ) -> JSONResponse:
        return error_response(
            409,
            "TRANSITION_FORBIDDEN",
            "Недопустимый переход",
            {
                "current_status": exc.current_status.value,
                "target_status": exc.target_status.value,
            },
        )

    @app.exception_handler(LessonNotFinishedError)
    async def _not_finished(_: Request, exc: LessonNotFinishedError) -> JSONResponse:
        return error_response(
            409,
            "LESSON_NOT_FINISHED",
            "Занятие ещё не закончилось",
            {
                "ends_at": to_iso_z(exc.ends_at, preserve_fraction=True),
                "now": to_iso_z(exc.now, preserve_fraction=True),
            },
        )
