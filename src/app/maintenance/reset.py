"""Восстановление исходных предметных данных."""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson
from app.maintenance.seed import SeedRecords, load_seed


async def restore_seed(
    session: AsyncSession,
    data: dict[str, SeedRecords],
) -> None:
    """Очистить данные и восстановить seed без завершения транзакции."""
    await session.execute(delete(Lesson))
    await session.execute(delete(Group))
    await load_seed(session, data)
