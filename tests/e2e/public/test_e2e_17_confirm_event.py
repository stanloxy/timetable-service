"""E2E-17. Подтверждение занятия и событие LessonConfirmed (FR-06, FR-13)."""

import uuid

import httpx
import pytest

from tests.e2e.broker import BrokerHelper
from tests.e2e.contract import ContractChecker
from tests.e2e.report import Recorder

ENVELOPE_KEYS = {
    "event_id",
    "event_type",
    "occurred_at",
    "idempotency_key",
    "producer",
    "version",
    "payload",
}


@pytest.mark.scenario(id="E2E-17", fr=["FR-06", "FR-13"], must=True)
async def test_confirm_publishes_exactly_one_event(
    api: httpx.AsyncClient,
    broker: BrokerHelper,
    ids: dict[str, str],
    contract: ContractChecker,
    record: Recorder,
) -> None:
    """Подтверждение публикует ровно одно LessonConfirmed; повтор — 409 без нового события."""
    record.expected(
        "200 CONFIRMED; одно событие LessonConfirmed (конверт платформы, "
        "occurred_at по часам сервиса, "
        "idempotency_key=lesson-confirmed:L1); повторный confirm → 409 TRANSITION_FORBIDDEN "
        "{CONFIRMED→CONFIRMED}, нового события нет"
    )

    confirmed = await api.post(f"/lessons/{ids['L1']}/confirm")
    record.actual(f"confirm → {confirmed.status_code}: {confirmed.text[:200]}")
    assert confirmed.status_code == 200, confirmed.text
    lesson = confirmed.json()
    contract.assert_schema(lesson, "Lesson")
    assert lesson["id"] == ids["L1"]
    assert lesson["status"] == "CONFIRMED"

    events = await broker.consume(timeout_seconds=5.0, max_messages=2)
    record.actual(f"{record.record.actual}; событий получено: {len(events)}")
    assert len(events) == 1, f"ожидалось одно событие, получено {len(events)}: {events}"
    event = events[0]
    assert set(event) == ENVELOPE_KEYS, f"конверт события: {sorted(event)}"
    uuid.UUID(event["event_id"])
    assert event["event_type"] == "LessonConfirmed"
    assert event["occurred_at"] == "2026-11-30T03:00:00Z"
    assert event["idempotency_key"] == f"lesson-confirmed:{ids['L1']}"
    assert event["producer"] == "timetable-service"
    assert event["version"] == 1
    payload = event["payload"]
    assert payload["lesson_id"] == ids["L1"]
    assert payload["group_id"] == ids["G1"]
    assert payload["instructor_id"] == ids["I1"]
    assert payload["classroom_id"] == ids["C1"]
    assert payload["format"] == "IN_PERSON"
    assert payload["starts_at"] == "2026-12-01T05:00:00Z"
    assert payload["ends_at"] == "2026-12-01T06:30:00Z"

    repeated = await api.post(f"/lessons/{ids['L1']}/confirm")
    record.actual(f"{record.record.actual}; повторный confirm → {repeated.status_code}")
    details = contract.assert_error(repeated, 409, "TRANSITION_FORBIDDEN")
    assert details == {"current_status": "CONFIRMED", "target_status": "CONFIRMED"}

    after_repeat = await broker.consume(timeout_seconds=3.0, max_messages=1)
    record.actual(f"{record.record.actual}; событий после повтора: {len(after_repeat)}")
    assert after_repeat == [], "после отклонённого confirm событий быть не должно"
