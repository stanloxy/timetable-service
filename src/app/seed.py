"""Seed: детерминированные фикстуры из ``seed/*.json`` (TASK.md, §3.5).

Каркас умеет читать файлы seed. Загрузка в БД (``load_seed``) появляется вместе с моделями:
её вызывают ``just seed`` (``python -m app.seed``), ``SEED_ON_START=1`` и ``POST /__test/reset``.
Загрузчик обязан быть идемпотентным (повторный запуск на уже засеянной БД не падает)
и обходить доменную валидацию: seed не должен зависеть от заглушки.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import make_engine, make_session_factory
from app.settings import get_settings

# Корень репозитория: src/app/seed.py → parents[2]. В образе это /app (editable-установка пакета).
SEED_DIR = Path(__file__).resolve().parents[2] / "seed"

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
    """Записать seed в БД поверх пустых таблиц.

    Реализуется автором сервиса после появления моделей. Договорённости: прямые INSERT без доменной
    валидации, фиксированные UUID из файлов, идемпотентность.
    """
    msg = "Загрузчик seed не реализован: см. src/app/seed.py и TASK.md, §3.5"
    raise NotImplementedError(msg)


async def main() -> int:
    """``python -m app.seed``: загрузить seed в БД из ``DATABASE_URL``."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    data = read_all()
    log.info("Прочитан seed: %s", {name: len(rows) for name, rows in data.items()})
    try:
        async with factory() as session:
            await load_seed(session, data)
            await session.commit()
    finally:
        await engine.dispose()
    log.info("Seed загружен")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
