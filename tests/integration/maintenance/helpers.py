"""Чтение фактического состояния для сравнения с seed."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import to_iso_z
from app.db.models import Group, Lesson


async def snapshot(
    session: AsyncSession,
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}

    for model in (Group, Lesson):
        rows = await session.execute(select(*model.__table__.columns).order_by(model.id))
        records: list[dict[str, object]] = []

        for row in rows.mappings():
            record: dict[str, object] = {}
            for key, value in row.items():
                if isinstance(value, UUID):
                    record[key] = str(value)
                elif isinstance(value, datetime):
                    record[key] = to_iso_z(value)
                else:
                    record[key] = value
            records.append(record)

        result[model.__tablename__] = records

    return result
