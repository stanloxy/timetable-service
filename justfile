# Команды проекта: `just` — список рецептов. Установка just — SCAFFOLD.md, раздел «Окружение».
# .env необязателен: если он есть, just загружает его в окружение рецептов (как и docker compose).

set dotenv-load := true
set positional-arguments := true
set shell := ["bash", "-euo", "pipefail", "-c"]

alias format := fmt

# Список рецептов
default:
    @just --list --unsorted

# Проверить окружение: Docker, Compose v2.20+, buildx 0.17+, uv 0.13+
doctor:
    #!/usr/bin/env bash
    set -uo pipefail
    status=0
    ok()   { printf '  OK    %s\n' "$*"; }
    fail() { printf '  FAIL  %s\n' "$*"; status=1; }
    clean() { sed -E 's/^v//; s/[+-].*$//' <<<"$1"; }
    ver_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

    if command -v docker >/dev/null 2>&1; then ok "$(docker --version)"; else fail "docker не найден"; fi
    if docker info >/dev/null 2>&1; then
        ok "Docker daemon доступен"
    else
        fail "Docker daemon недоступен: запущен ли сервис docker, состоит ли пользователь в группе docker"
    fi
    compose="$(docker compose version --short 2>/dev/null || true)"
    if [ -z "$compose" ]; then
        fail "docker compose (v2) не найден: нужен плагин Docker Compose v2.20+"
    elif ver_ge "$(clean "$compose")" 2.20.0; then
        ok "docker compose $compose"
    else
        fail "docker compose $compose: нужна версия 2.20+"
    fi
    buildx="$(docker buildx version 2>/dev/null | awk '{print $2}')"
    if [ -z "$buildx" ]; then
        fail "docker buildx не найден: Dockerfile использует BuildKit (RUN --mount), нужен buildx 0.17+"
    elif ver_ge "$(clean "$buildx")" 0.17.0; then
        ok "docker buildx $buildx"
    else
        fail "docker buildx $buildx: нужна 0.17+, иначе compose build падает («requires buildx 0.17.0»)"
    fi
    uv="$(uv --version 2>/dev/null | awk '{print $2}')"
    if [ -z "$uv" ]; then
        fail "uv не найден"
    elif ver_ge "$(clean "$uv")" 0.13.0; then
        ok "uv $uv"
    else
        fail "uv $uv: нужна 0.13+ (uv self update)"
    fi
    if [ "$status" -ne 0 ]; then
        echo
        echo "Как установить недостающее — SCAFFOLD.md, раздел «Окружение»."
    fi
    exit "$status"

# Собрать и поднять стек, дождаться healthcheck всех сервисов (аргументы — docker compose up)
up *args:
    docker compose up -d --build --wait "$@"

# Остановить стек и удалить тома
down:
    docker compose down -v --remove-orphans

# Логи сервиса (по умолчанию app)
logs service="app":
    docker compose logs -f "$1"

# Состояние контейнеров
ps:
    docker compose ps

# Применить миграции в контейнере app (entrypoint делает это и при старте)
migrate:
    docker compose exec app alembic upgrade head

# Создать локальные настройки тестовой БД; существующий файл не перезаписывается
test-db-init:
    #!/usr/bin/env bash
    set -euo pipefail
    umask 077
    if [[ -e .env.test ]]; then
        echo '.env.test уже существует; файл оставлен без изменений'
        exit 0
    fi
    password="$(openssl rand -hex 32)"
    set -o noclobber
    printf 'TEST_POSTGRES_USER=wa_test\nTEST_POSTGRES_DB=wa_wp01_test\nTEST_POSTGRES_PORT=55433\nTEST_POSTGRES_PASSWORD=%s\n' "$password" > .env.test
    echo 'Создан .env.test с правами 600; пароль не выводится'

# Поднять отдельную временную PostgreSQL и дождаться готовности
test-db-up:
    @docker compose --env-file .env.test -f compose.test.yml -p timetable-service-test up -d --wait

# Остановить тестовую PostgreSQL и удалить контейнер; её данные будут потеряны
test-db-down:
    @docker compose --env-file .env.test -f compose.test.yml -p timetable-service-test down

# Посмотреть состояние только тестовой PostgreSQL
test-db-ps:
    @docker compose --env-file .env.test -f compose.test.yml -p timetable-service-test ps

# Применить существующие миграции только к тестовой БД
test-db-migrate:
    @uv run python tools/test_db.py upgrade head

# Создать ревизию по моделям и тестовой БД; новую ревизию НЕ применяет
test-db-migration message:
    @uv run python tools/test_db.py revision --autogenerate -m "$1"
    uv run ruff format migrations/versions
    uv run ruff check --fix migrations/versions

# Создать миграцию autogenerate при поднятом стеке: just migration "create lessons"
migration message:
    DATABASE_URL="${HOST_DATABASE_URL:-postgresql+asyncpg://wa:wa@localhost:5432/wa}" uv run alembic revision --autogenerate -m "$1"
    uv run ruff format migrations/versions
    uv run ruff check --fix migrations/versions

# Загрузить seed в БД контейнера app
seed:
    docker compose exec app python -m app.seed

# Модульные тесты (аргументы передаются pytest)
test *args:
    uv run pytest tests/unit "$@"

# Интеграционные тесты против заранее подготовленной тестовой PostgreSQL
test-db-test *args:
    uv run pytest tests/integration "$@"

# ruff: правила и форматирование
lint:
    uv run ruff check .
    uv run ruff format --check .

# ruff: отформатировать и исправить автоматически исправимое
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# mypy strict
typecheck:
    uv run mypy

# Всё, что проверяет CI
check: lint typecheck test

# Публичные e2e против поднятого стека (just up); отчёт — e2e-report.json
e2e-public *args:
    uv run pytest tests/e2e/public -p no:cacheprovider --e2e-report e2e-report.json "$@"

# Локальная настройка git: шаблон сообщения коммита и хук commit-msg из репозитория (CONTRIBUTING.md)
setup:
    git config commit.template .gitmessage
    git config core.hooksPath .githooks
    chmod +x .githooks/* tools/merge_change.sh tools/lint_commits.py
    @echo "git настроен: commit.template=.gitmessage, core.hooksPath=.githooks"

# Проверить историю коммитов от scaffold-base до HEAD по CONTRIBUTING.md (аргументы — lint_commits.py)
lint-commits *args:
    python3 tools/lint_commits.py "$@"

# Слить завершённый пакет change/<id> в master merge-коммитом --no-ff: just merge-change wp01-load-seed-data
merge-change id:
    bash tools/merge_change.sh "$1"
