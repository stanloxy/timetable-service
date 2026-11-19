"""Единая абстракция «сейчас».

Правило проекта: ``datetime.now()`` допустим только внутри этого модуля. Весь остальной код
(обработчики, доменные правила, фоновые задачи, публикация событий) получает время через ``Clock``.
Тестовые эндпоинты ``/__test/time`` управляют экземпляром ``AdjustableClock``.
"""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Источник текущего времени."""

    def now(self) -> datetime:
        """Текущее время, aware, в UTC."""
        ...


class SystemClock:
    """Системные часы."""

    def now(self) -> datetime:
        """Системное время в UTC."""
        return datetime.now(UTC)


class AdjustableClock:
    """Часы, которые можно зафиксировать на заданном моменте и вернуть к системным.

    После ``freeze`` время не идёт: каждый вызов ``now`` возвращает одно и то же значение,
    пока не вызван ``reset``. Это намеренно: сценарии e2e детерминированы при одинаковых часах.
    """

    def __init__(self, system: Clock | None = None) -> None:
        self._system: Clock = system or SystemClock()
        self._frozen: datetime | None = None

    def now(self) -> datetime:
        """Зафиксированное время, если оно установлено, иначе системное."""
        if self._frozen is not None:
            return self._frozen
        return self._system.now()

    def freeze(self, moment: datetime) -> None:
        """Зафиксировать часы на ``moment`` (должен быть aware; приводится к UTC)."""
        if moment.tzinfo is None:
            msg = "Момент времени должен содержать смещение часового пояса"
            raise ValueError(msg)
        self._frozen = moment.astimezone(UTC)

    def reset(self) -> None:
        """Вернуться к системным часам."""
        self._frozen = None

    @property
    def is_frozen(self) -> bool:
        """Установлено ли фиксированное время."""
        return self._frozen is not None


def to_iso_z(moment: datetime, *, preserve_fraction: bool = False) -> str:
    """ISO 8601 в UTC с суффиксом ``Z`` — формат времени во всех ответах и событиях платформы."""
    if moment.tzinfo is None:
        msg = "Ожидается aware datetime"
        raise ValueError(msg)
    timespec = "auto" if preserve_fraction else "seconds"
    return moment.astimezone(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")
