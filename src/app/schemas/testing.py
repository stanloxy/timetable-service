from pydantic import AwareDatetime, BaseModel, ConfigDict


class TestTime(BaseModel):
    """Тело и ответ ``/__test/time``. Время без смещения отклоняется (422 ``VALIDATION_ERROR``)."""

    model_config = ConfigDict(extra="forbid")

    now: AwareDatetime


class JobResult(BaseModel):
    """Ответ ``/__test/jobs/{job_name}/run``."""

    processed: int
