import logging
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from app.errors import install_error_handlers
from app.services.exceptions import ResourceNotFoundError


@pytest.mark.parametrize("unexpected", [True, False])
async def test_error_logging(
    caplog: pytest.LogCaptureFixture,
    unexpected: bool,
) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/failure")
    async def failure() -> None:
        if unexpected:
            raise RuntimeError("PRIVATE_ERROR_MARKER")
        raise ResourceNotFoundError(
            "group",
            UUID("9a000000-0000-4000-8000-000000000099"),
        )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="app.errors"):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/failure")

    records = [record for record in caplog.records if record.name == "app.errors"]

    if unexpected:
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "PRIVATE_ERROR_MARKER" not in response.text
        assert len(records) == 1
        assert records[0].exc_info is not None
    else:
        assert response.status_code == 404
        assert records == []
