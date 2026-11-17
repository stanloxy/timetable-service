"""Запуск Alembic, seed или приложения с подключением тестовой БД из .env.test."""

import os
import sys
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env.test"


class TestDatabaseSettings(BaseSettings):
    """Единый набор параметров тестовой PostgreSQL для команд с хоста."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_prefix="TEST_POSTGRES_",
        extra="ignore",
    )

    user: str = Field(min_length=1)
    password: SecretStr = Field(min_length=1)
    db: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


def load_test_database_url() -> URL:
    """Прочитать подключение тестовой БД, не раскрывая пароль."""
    if not ENV_FILE.is_file():
        raise ValueError("Нет .env.test. Сначала выполните just test-db-init.")
    try:
        settings = TestDatabaseSettings()
    except ValidationError:
        raise ValueError(
            "Некорректный .env.test: проверьте TEST_POSTGRES_USER, "
            "TEST_POSTGRES_PASSWORD, TEST_POSTGRES_DB "
            "и TEST_POSTGRES_PORT (1–65535)."
        ) from None

    return URL.create(
        "postgresql+asyncpg",
        username=settings.user,
        password=settings.password.get_secret_value(),
        host="127.0.0.1",
        port=settings.port,
        database=settings.db,
    )


def main() -> int:
    """Запустить выбранную команду без вывода строки подключения."""
    try:
        url = load_test_database_url()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.chdir(REPO_ROOT)

    if sys.argv[1:] == ["--seed"]:
        os.execvpe(
            sys.executable,
            [sys.executable, "-m", "app.maintenance.seed"],
            environment,
        )

    if sys.argv[1:] == ["--serve"]:
        environment["TEST_MODE"] = "1"
        os.execvpe(
            sys.executable,
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ],
            environment,
        )

    os.execvpe("alembic", ["alembic", *sys.argv[1:]], environment)


if __name__ == "__main__":
    raise SystemExit(main())
