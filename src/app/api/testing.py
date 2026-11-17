"""Тестовые эндпоинты ``/__test/*`` (TASK.md, §3.6). Доступны только при ``TEST_MODE=1``, иначе 404.

Управление часами (``/__test/time``), запуск зарегистрированных фоновых задач и сброс данных.
``POST /__test/reset`` вызывает подключённую в build_context операцию ``AppContext.reset_state``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.clock import to_iso_z
from app.context import AppContext, get_context
from app.errors import ApiError, not_found
from app.jobs import UnknownJobError


def require_test_mode(request: Request) -> AppContext:
    """Пропустить запрос только при ``TEST_MODE=1``; иначе маршрут «не существует»."""
    context = get_context(request)
    if not context.settings.test_mode:
        raise not_found("Ресурс не найден")
    return context


TestContext = Annotated[AppContext, Depends(require_test_mode)]

router = APIRouter(prefix="/__test", tags=["test-mode"])


class TestTime(BaseModel):
    """Тело и ответ ``/__test/time``. Время без смещения отклоняется (422 ``VALIDATION_ERROR``)."""

    model_config = ConfigDict(extra="forbid")

    now: AwareDatetime


class JobResult(BaseModel):
    """Ответ ``/__test/jobs/{job_name}/run``."""

    processed: int


@router.get("/time")
async def get_time(context: TestContext) -> dict[str, str]:
    """Текущее время часов сервиса."""
    return {"now": to_iso_z(context.clock.now())}


@router.put("/time")
async def set_time(body: TestTime, context: TestContext) -> dict[str, str]:
    """Зафиксировать часы сервиса на заданном моменте."""
    context.clock.freeze(body.now)
    return {"now": to_iso_z(context.clock.now())}


@router.delete("/time", status_code=204, response_class=Response)
async def reset_time(context: TestContext) -> Response:
    """Вернуть системные часы."""
    context.clock.reset()
    return Response(status_code=204)


@router.post("/jobs/{job_name}/run", response_model=JobResult)
async def run_job(job_name: str, context: TestContext) -> JobResult:
    """Синхронно выполнить фоновую задачу. Неизвестное имя — 404 ``NOT_FOUND``."""
    try:
        processed = await context.jobs.run(job_name)
    except UnknownJobError:
        raise not_found("Фоновая задача не найдена", job_name=job_name) from None
    return JobResult(processed=processed)


@router.post("/reset", status_code=204, response_class=Response)
async def reset_state(context: TestContext) -> Response:
    """Очистить данные и выполнить seed. Часы не меняются."""
    if context.reset_state is None:
        raise ApiError(
            501,
            "NOT_IMPLEMENTED",
            "Сброс данных не реализован: задайте AppContext.reset_state в src/app/main.py",
        )
    await context.reset_state()
    return Response(status_code=204)
