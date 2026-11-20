"""Проверки живости и готовности (TASK.md, §3.6).

``/health/live`` — 200, пока процесс жив. ``/health/ready`` — 200
``{"status":"ok","db":"ok","broker":"ok"}``, если доступны БД и брокер; иначе 503
``{"status":"degraded", ...}`` со статусом каждой зависимости.
Заглушка соседнего сервиса в readiness не входит.
"""

import asyncio
from collections.abc import Awaitable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.context import get_context
from app.db.session import check_database
from app.schemas.health import DependencyStatus, Liveness, Readiness

router = APIRouter(prefix="/health", tags=["health"])

READINESS_TIMEOUT_SECONDS = 2.0


async def _probe(check: Awaitable[bool]) -> DependencyStatus:
    try:
        ok = await asyncio.wait_for(check, timeout=READINESS_TIMEOUT_SECONDS)
    except Exception:
        return "fail"
    return "ok" if ok else "fail"


@router.get("/live", response_model=Liveness)
async def live() -> Liveness:
    """Процесс жив."""
    return Liveness()


@router.get("/ready", response_model=Readiness, responses={503: {"model": Readiness}})
async def ready(request: Request) -> JSONResponse:
    """Готовность: БД и брокер проверяются параллельно, каждая — с собственным таймаутом."""
    context = get_context(request)
    db_status, broker_status = await asyncio.gather(
        _probe(check_database(context.engine)),
        _probe(context.broker_probe.ping()),
    )
    readiness = Readiness(
        status="ok" if db_status == "ok" and broker_status == "ok" else "degraded",
        db=db_status,
        broker=broker_status,
    )
    status_code = 200 if readiness.status == "ok" else 503
    return JSONResponse(status_code=status_code, content=readiness.model_dump())
