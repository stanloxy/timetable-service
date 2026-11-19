from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse


def error_payload(
    code: str, message: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Тело ответа с ошибкой."""
    return {"error": {"code": code, "message": message, "details": dict(details or {})}}


def error_response(
    status_code: int, code: str, message: str, details: Mapping[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_payload(code, message, details))
