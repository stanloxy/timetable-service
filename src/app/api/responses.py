from app.schemas.errors import ErrorResponse


def error_responses(*statuses: int) -> dict[int | str, dict[str, object]]:
    """Описать ответы с ошибками в генерируемой HTTP-схеме."""
    return {status: {"model": ErrorResponse} for status in statuses}
