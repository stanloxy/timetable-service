from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.context import AppContext
from app.db.models import Lesson
from app.enums.lessons import LessonFormat, LessonStatus
from tests.e2e.assignment import IDS
from tests.e2e.contract import ContractChecker

_START = datetime(2026, 12, 10, 5, tzinfo=UTC)


def _lesson(
    lesson_id: UUID,
    *,
    group: str = "G1",
    instructor: str = "I1",
    classroom: str = "C1",
    status: LessonStatus = LessonStatus.PLANNED,
    start: datetime = _START,
) -> Lesson:
    return Lesson(
        id=lesson_id,
        group_id=UUID(IDS[group]),
        instructor_id=UUID(IDS[instructor]),
        classroom_id=UUID(IDS[classroom]),
        status=status,
        format=LessonFormat.IN_PERSON,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        created_at=_START,
        updated_at=_START,
    )


async def test_list_combines_filters_and_preserves_total(
    api_client: tuple[httpx.AsyncClient, AppContext], contract: ContractChecker
) -> None:
    http, context = api_client
    context.settings.test_mode = False
    later, first, second = sorted(uuid4() for _ in range(3))
    async with context.session_factory.begin() as session:
        session.add_all(
            [
                _lesson(second),
                _lesson(first),
                _lesson(later, start=_START + timedelta(minutes=30)),
                _lesson(uuid4(), start=_START - timedelta(minutes=30)),
                _lesson(uuid4(), start=_START + timedelta(hours=1)),
                _lesson(uuid4(), group="G2"),
                _lesson(uuid4(), instructor="I2"),
                _lesson(uuid4(), classroom="C2"),
                _lesson(uuid4(), status=LessonStatus.CONFIRMED),
            ]
        )

    params = {
        "group_id": IDS["G1"],
        "instructor_id": IDS["I1"],
        "classroom_id": IDS["C1"],
        "status": "PLANNED",
        "from": "2026-12-10T10:00:00+05:00",
        "to": "2026-12-10T06:00:00Z",
        "limit": "1",
    }
    for offset, expected in [
        (0, [first]),
        (1, [second]),
        (2, [later]),
        (3, []),
        (2**63, []),
    ]:
        response = await http.get("/lessons", params={**params, "offset": str(offset)})
        assert response.status_code == 200, response.text
        page = response.json()
        contract.assert_schema(page, "LessonPage")
        assert page["total"] == 3
        assert [item["id"] for item in page["items"]] == list(map(str, expected))


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"from": "2026-12-03T08:00:00Z"}, ["L7"]),
        ({"to": "2026-11-30T04:00:00Z"}, ["L8"]),
        ({"from": "2026-12-01T05:00:00Z", "to": "2026-12-01T05:00:00Z"}, []),
        ({"from": "2026-12-02T00:00:00Z", "to": "2026-12-01T00:00:00Z"}, []),
        ({"group_id": IDS["G_MISSING"]}, []),
        ((("status", "CANCELLED"), ("unknown", "ignored"), ("status", "RESCHEDULED")), ["L6"]),
    ],
)
async def test_list_query_boundaries(
    api_client: tuple[httpx.AsyncClient, AppContext],
    params: dict[str, str] | tuple[tuple[str, str], ...],
    expected: list[str],
) -> None:
    http, _ = api_client
    response = await http.get("/lessons", params=params)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == len(expected)
    assert [item["id"] for item in page["items"]] == [IDS[key] for key in expected]


async def test_list_defaults_to_fifty_from_the_start(
    api_client: tuple[httpx.AsyncClient, AppContext],
    seeded_factory: async_sessionmaker[AsyncSession],
) -> None:
    http, _ = api_client
    ids = sorted(uuid4() for _ in range(51))
    async with seeded_factory.begin() as session:
        session.add_all(_lesson(lesson_id) for lesson_id in reversed(ids))

    params = {"from": _START.isoformat()}
    response = await http.get("/lessons", params=params)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 51
    assert [item["id"] for item in page["items"]] == list(map(str, ids[:50]))

    response = await http.get("/lessons", params={**params, "limit": "200"})
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == list(map(str, ids))
