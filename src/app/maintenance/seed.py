"""Seed: детерминированные фикстуры из ``seed/*.json`` (TASK.md, §3.5).

Каркас умеет читать файлы seed. Загрузка в БД (``load_seed``) появляется вместе с моделями:
Её вызывают ``just seed`` (``python -m app.maintenance.seed``), ``SEED_ON_START=1``
и ``POST /__test/reset``.
Загрузчик обязан быть идемпотентным (повторный запуск на уже засеянной БД не падает)
и обходить доменную валидацию: seed не должен зависеть от заглушки.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Group, Lesson
from app.db.session import make_engine, make_session_factory, session_scope
from app.settings import get_settings

# Корень репозитория: src/app/maintenance/seed.py → parents[3]. В образе это /app.
SEED_DIR = Path(__file__).resolve().parents[3] / "seed"

log = logging.getLogger(__name__)

SeedRecords = list[dict[str, Any]]


def read_seed_file(name: str, seed_dir: Path = SEED_DIR) -> SeedRecords:
    """Прочитать ``seed/<name>.json``: список объектов с фиксированными UUID."""
    path = seed_dir / f"{name}.json"
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        msg = f"{path}: ожидается список записей"
        raise ValueError(msg)
    records: SeedRecords = []
    for item in data:
        if not isinstance(item, dict):
            msg = f"{path}: каждая запись должна быть объектом"
            raise ValueError(msg)
        records.append(item)
    return records


def read_all(seed_dir: Path = SEED_DIR) -> dict[str, SeedRecords]:
    """Все файлы seed по имени файла без расширения."""
    return {
        path.stem: read_seed_file(path.stem, seed_dir) for path in sorted(seed_dir.glob("*.json"))
    }


async def load_seed(session: AsyncSession, data: dict[str, SeedRecords]) -> None:
    """Добавить отсутствующие seed-записи без изменения существующих."""
    for record in data["groups"]:
        row = record.copy()
        row["id"] = UUID(row["id"])

        statement = insert(Group).values(row).on_conflict_do_nothing(index_elements=["id"])
        await session.execute(statement)

    uuid_fields = (
        "id",
        "group_id",
        "instructor_id",
        "classroom_id",
        "rescheduled_from_id",
    )
    datetime_fields = (
        "starts_at",
        "ends_at",
        "created_at",
        "updated_at",
    )

    # В выданном seed исходное занятие L6 расположено перед преемником L7.
    for record in data["lessons"]:
        row = record.copy()

        for field in uuid_fields:
            if row[field] is not None:
                row[field] = UUID(row[field])

        for field in datetime_fields:
            row[field] = datetime.fromisoformat(row[field])

        statement = insert(Lesson).values(row).on_conflict_do_nothing(index_elements=["id"])
        await session.execute(statement)


async def main() -> int:
    """Загрузить seed в БД из DATABASE_URL."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    engine = make_engine(settings.database_url)
    try:
        factory = make_session_factory(engine)
        data = read_all()
        log.info(
            "Прочитан seed: %s",
            {name: len(rows) for name, rows in data.items()},
        )

        async with session_scope(factory) as session:
            await load_seed(session, data)
    finally:
        await engine.dispose()
    log.info("Seed загружен")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
