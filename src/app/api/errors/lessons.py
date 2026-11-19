from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors.responses import error_response
from app.services.exceptions.lessons import (
    ClassroomRequiredError,
    GroupNotFoundError,
    LessonConflictError,
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
