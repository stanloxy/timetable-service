from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.errors.responses import error_response
from app.services.exceptions.people import (
    ClassroomNotFoundError,
    InstructorNotFoundError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)


def install_people_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(InstructorNotFoundError)
    async def _instructor_not_found(_: Request, exc: InstructorNotFoundError) -> JSONResponse:
        return error_response(
            422,
            "INSTRUCTOR_NOT_FOUND",
            "Преподаватель не найден",
            {"instructor_id": str(exc.instructor_id)},
        )

    @app.exception_handler(ClassroomNotFoundError)
    async def _classroom_not_found(_: Request, exc: ClassroomNotFoundError) -> JSONResponse:
        return error_response(
            422,
            "CLASSROOM_NOT_FOUND",
            "Аудитория не найдена",
            {"classroom_id": str(exc.classroom_id)},
        )

    @app.exception_handler(UpstreamUnavailableError)
    async def _upstream_unavailable(_: Request, __: UpstreamUnavailableError) -> JSONResponse:
        return error_response(
            502,
            "UPSTREAM_UNAVAILABLE",
            "Сервис людей и аудиторий недоступен",
            {"upstream": "people-stub"},
        )

    @app.exception_handler(UpstreamTimeoutError)
    async def _upstream_timeout(_: Request, exc: UpstreamTimeoutError) -> JSONResponse:
        return error_response(
            504,
            "UPSTREAM_TIMEOUT",
            "Сервис людей и аудиторий не ответил вовремя",
            {"upstream": "people-stub", "timeout_ms": exc.timeout_ms},
        )
