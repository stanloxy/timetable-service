"""Занятия и ссылки на их участников и предшественников."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Lesson(Base):
    """Занятие; преподаватель и аудитория принадлежат внешнему сервису."""

    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PLANNED', 'CONFIRMED', 'IN_PROGRESS', "
            "'COMPLETED', 'CANCELLED', 'RESCHEDULED')",
            name="ck_lessons_status",
        ),
        CheckConstraint("format IN ('IN_PERSON', 'ONLINE')", name="ck_lessons_format"),
        CheckConstraint(
            "ends_at - starts_at BETWEEN INTERVAL '30 minutes' AND INTERVAL '8 hours'",
            name="ck_lessons_duration",
        ),
        CheckConstraint(
            "(format = 'ONLINE' AND classroom_id IS NULL) OR "
            "(format = 'IN_PERSON' AND classroom_id IS NOT NULL)",
            name="ck_lessons_format_classroom",
        ),
        CheckConstraint("rescheduled_from_id <> id", name="ck_lessons_no_self_reschedule"),
        UniqueConstraint("rescheduled_from_id", name="uq_lessons_rescheduled_from_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    group_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("groups.id", name="fk_lessons_group_id", ondelete="NO ACTION"),
        nullable=False,
    )
    instructor_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    classroom_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rescheduled_from_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("lessons.id", name="fk_lessons_rescheduled_from_id", ondelete="NO ACTION"),
        nullable=True,
    )
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
