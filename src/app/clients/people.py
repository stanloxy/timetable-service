import asyncio
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from app.clients.people_models import Availability, Classroom, Instructor


class PeopleUnavailableError(Exception):
    """Заглушка не предоставила пригодный ответ."""


class PeopleTimeoutError(Exception):
    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        super().__init__(f"people-stub request exceeded {timeout_ms} ms")


class PeopleClient:
    def __init__(self, http: httpx.AsyncClient, timeout_ms: int) -> None:
        self._http = http
        self._timeout_ms = timeout_ms

    async def get_instructor(self, instructor_id: UUID) -> Instructor | None:
        return await self._get(f"/instructors/{instructor_id}", Instructor)

    async def get_availability(self, instructor_id: UUID) -> Availability | None:
        return await self._get(f"/instructors/{instructor_id}/availability", Availability)

    async def get_classroom(self, classroom_id: UUID) -> Classroom | None:
        return await self._get(f"/classrooms/{classroom_id}", Classroom)

    async def _get[ResponseModel: BaseModel](
        self, path: str, model: type[ResponseModel]
    ) -> ResponseModel | None:
        try:
            async with asyncio.timeout(self._timeout_ms / 1000):
                response = await self._http.get(path, timeout=None)
        except TimeoutError as exc:
            raise PeopleTimeoutError(self._timeout_ms) from exc
        except httpx.RequestError as exc:
            raise PeopleUnavailableError("people-stub request failed") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.status_code != httpx.codes.OK:
            raise PeopleUnavailableError(f"people-stub returned HTTP {response.status_code}")
        try:
            return model.model_validate_json(response.content, strict=True)
        except ValidationError as exc:
            raise PeopleUnavailableError("people-stub returned an invalid response") from exc
