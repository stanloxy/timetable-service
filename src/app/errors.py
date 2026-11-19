"""Единый формат ошибок платформы: ``{"error": {"code", "message", "details"}}``.

Соглашение пула (TASK.md, §3.3):

- 400 ``BAD_REQUEST`` — синтаксически невалидный запрос: невалидный JSON, неверный тип поля;
- 404 ``NOT_FOUND`` — ресурс из пути не найден (в том числе неизвестный маршрут);
- 422 ``VALIDATION_ERROR`` — семантически невалидные данные, ``details.fields`` — поле → сообщение;
- ожидаемые ошибки сценариев преобразуются в HTTP-ответы обработчиками ниже.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors.lessons import install_lesson_error_handlers
from app.api.errors.people import install_people_error_handlers
from app.api.errors.responses import error_payload as error_payload
from app.api.errors.responses import error_response as error_response
from app.services.exceptions.resources import ResourceNotFoundError

log = logging.getLogger(__name__)

# Типы ошибок pydantic, которые означают «не тот тип/формат JSON», а не «неверное значение».
_SYNTACTIC_ERROR_TYPES: frozenset[str] = frozenset(
    {
        "json_invalid",
        "json_type",
        "model_type",
        "model_attributes_type",
        "dict_type",
        "list_type",
        "string_type",
        "int_type",
        "int_parsing",
        "float_type",
        "float_parsing",
        "bool_type",
        "bool_parsing",
        "uuid_type",
        "datetime_type",
        "date_type",
        "none_required",
    }
)

_HTTP_STATUS_CODES: Mapping[int, str] = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    415: "UNSUPPORTED_MEDIA_TYPE",
}


class ApiError(Exception):
    """Ошибка, которую сервис отдаёт клиенту в едином формате."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details or {})


def not_found(message: str = "Ресурс не найден", **details: Any) -> ApiError:
    """Фабрика 404 ``NOT_FOUND``."""
    return ApiError(404, "NOT_FOUND", message, details)


def _field_name(loc: Sequence[Any]) -> str:
    parts = [str(part) for part in loc]
    if parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts = parts[1:]
    if not parts or all(part.isdigit() for part in parts):
        # Ошибка разбора самого JSON: pydantic указывает позицию, а не поле.
        return "body"
    return ".".join(parts)


def classify_validation_error(
    errors: Sequence[Mapping[str, Any]],
) -> tuple[int, str, dict[str, Any]]:
    """Разложить ошибки pydantic на (HTTP-статус, code, details) по соглашению пула."""
    if any(str(err.get("type", "")) in _SYNTACTIC_ERROR_TYPES for err in errors):
        problems = [
            {"field": _field_name(err.get("loc", ())), "type": str(err.get("type", ""))}
            for err in errors
        ]
        return 400, "BAD_REQUEST", {"errors": problems}
    fields = {_field_name(err.get("loc", ())): str(err.get("msg", "")) for err in errors}
    return 422, "VALIDATION_ERROR", {"fields": fields}


def install_error_handlers(app: FastAPI) -> None:
    """Подключить обработчики, приводящие все ошибки к единому формату."""
    install_lesson_error_handlers(app)
    install_people_error_handlers(app)

    @app.exception_handler(ResourceNotFoundError)
    async def _resource_not_found(
        _: Request,
        exc: ResourceNotFoundError,
    ) -> JSONResponse:
        messages = {
            "group": "Группа не найдена",
            "lesson": "Занятие не найдено",
        }
        return error_response(
            404,
            "NOT_FOUND",
            messages[exc.resource],
            {f"{exc.resource}_id": str(exc.resource_id)},
        )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        status_code, code, details = classify_validation_error(exc.errors())
        message = "Невалидный запрос" if status_code == 400 else "Невалидные данные"
        return error_response(status_code, code, message, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Ошибка HTTP"
        return error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Необработанное исключение не должно отдавать клиенту текст трассировки.
        log.error(
            "Unhandled error during %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return error_response(500, "INTERNAL_ERROR", "Внутренняя ошибка сервиса")
