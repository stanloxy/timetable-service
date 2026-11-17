"""Общий базовый класс ORM-моделей."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Metadata моделей для Alembic и приложения."""
