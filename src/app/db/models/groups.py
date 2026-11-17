"""Группы слушателей, принадлежащие сервису расписания."""

from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Group(Base):
    """Группа с положительным числом слушателей."""

    __tablename__ = "groups"
    __table_args__ = (CheckConstraint("size > 0", name="ck_groups_positive_size"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
