"""Допустимые статусы и форматы занятий."""

from enum import StrEnum


class LessonStatus(StrEnum):
    """Состояния жизненного цикла занятия."""

    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class LessonFormat(StrEnum):
    """Форматы проведения занятия."""

    IN_PERSON = "IN_PERSON"
    ONLINE = "ONLINE"
