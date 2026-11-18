from typing import Literal

from pydantic import BaseModel

DependencyStatus = Literal["ok", "fail"]


class Liveness(BaseModel):
    """Ответ ``/health/live``."""

    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    """Ответ ``/health/ready``."""

    status: Literal["ok", "degraded"]
    db: DependencyStatus
    broker: DependencyStatus
