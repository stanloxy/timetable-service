# Каркас (scaffold) timetable-service

Что уже сделано и как это устроено. Базовый коммит помечен тегом `scaffold-base`; diff против него —
вход проверки. Файлы каркаса можно менять, если это нужно для задачи; конфигурацию `ruff` и `mypy`
в `pyproject.toml` ослаблять нельзя.

## Окружение

| Инструмент | Версия | Зачем |
| --- | --- | --- |
| Docker Engine + Docker Compose | Compose v2.20+ | стек; `depends_on.required` в `docker-compose.yml` |
| docker buildx | 0.17+ | docker compose собирает образы через buildx (bake); Dockerfile использует BuildKit (`RUN --mount` для кэша uv). Со старым buildx `docker compose up --build` падает с «compose build requires buildx 0.17.0 or later» |
| uv | 0.13+ | зависимости, запуск ruff/mypy/pytest; в образе — та же минорная версия (`ghcr.io/astral-sh/uv:0.13`) |
| just | любая актуальная | команды проекта (`justfile`) |

Проверка: `just doctor`. Установка недостающего:

- **Docker Desktop** (macOS, Windows) уже содержит Compose и buildx нужных версий.
- **Linux, Docker из официального репозитория Docker**: `sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`.
- **Debian/Ubuntu/Kali, Docker из репозитория дистрибутива** (`docker.io`): `sudo apt update && sudo apt install docker-buildx`, затем `docker buildx version` (в Kali rolling — 0.29). Если версия ниже 0.17 (так в Debian 13: 0.13), поставьте Docker из официального репозитория Docker.
- **just**: `uv tool install rust-just` (любая ОС, нужен только uv), или пакет `just` из репозитория дистрибутива (`sudo apt install just`, `brew install just`, `winget install Casey.Just`).

## Состав

| Что | Где | Состояние |
| --- | --- | --- |
| Зависимости, ruff, mypy strict, pytest | `pyproject.toml`, `uv.lock` | готово; `uv sync` ставит группы dev и e2e |
| Пакет приложения | `src/app/` | src-layout: тесты и инструменты импортируют установленный пакет `app` |
| Образ приложения | `Dockerfile`, `docker/entrypoint.sh` | готово: multi-stage на `python:3.12-slim-trixie` по руководству uv (cache и bind mount'ы BuildKit), `uv sync --locked`, миграции при старте |
| Стек | `docker-compose.yml` | готово: `app`, `postgres`, `people-stub`, `rabbitmq` (по умолчанию), `kafka` (профиль `kafka`) |
| Переменные | `.env.example` | справочник; `.env` не нужен — значения по умолчанию в `docker-compose.yml` и `src/app/settings.py` |
| Команды | `justfile` | `doctor`, `up`, `down`, `logs`, `ps`, `migrate`, `migration`, `seed`, `test`, `lint`, `fmt`, `typecheck`, `check`, `e2e-public`, `setup`, `lint-commits`, `merge-change` |
| Процесс | `CONTRIBUTING.md`, `.gitmessage`, `.githooks/commit-msg`, `tools/` | пакеты работ и ветки, Conventional Commits, слияние `--no-ff`, журнал времени; проверка истории `just lint-commits` |
| CI | `.github/workflows/ci.yml`, `.gitlab-ci.yml` | lint + typecheck + test (+ сборка образа в GitHub Actions), проверка истории коммитов |
| Настройки | `src/app/settings.py` | все переменные из `.env.example` |
| БД | `src/app/db/`, `migrations/` | движок и сессии в `session.py`, `Base` в `base.py`, модели Group/Lesson и предметные миграции после `0001` |
| Часы | `src/app/clock.py` | `Clock`, `SystemClock`, `AdjustableClock`, `to_iso_z` |
| Ошибки | `src/app/errors.py` | единый формат; 400/404/422 по соглашению пула; `ApiError` для предметных кодов |
| Health | `src/app/api/health.py` | `/health/live`; `/health/ready` проверяет БД, брокер — `fail` до подключения |
| Тестовый режим | `src/app/api/testing.py`, `src/app/jobs.py` | время и запуск зарегистрированных задач работают; reset подключён в build_context, восстанавливает seed атомарно и сохраняет часы; без callback остаётся 501 |
| Seed | `seed/*.json`, `src/app/maintenance/seed.py`, `reset.py` | идемпотентная загрузка отсутствующих строк; reset очищает данные и восстанавливает исходный seed |
| Заглушка | `stubs/people-stub/` | готова: фикстуры, режимы отказов (`stub.env`), `/__stub/config`, `/__stub/stats` |
| Клиент заглушки | `src/app/clients/people.py`, `src/app/services/lesson_reference_data.py` | три типизированных запроса, таймаут на вызов, параллельная сборка данных |
| E2E-хелперы | `tests/e2e/` | клиенты, брокер (RabbitMQ и Kafka), проверка схем из `openapi.yaml`, отчёт JSON |
| Публичные e2e | `tests/e2e/public/` | сценарии из Приложения B задания; скрытый набор устроен так же |
| OpenSpec | `openspec/` | инициализирован (`config.yaml`, `specs/`, `changes/`) |

## Точки расширения

Места подключения помечены в коде комментарием `# ---> точка расширения`.
Модели, миграции и seed/reset уже добавлены; ниже также описано их дальнейшее расширение.
Согласованная целевая структура и правила — в `AGENTS.md`; задачи чтения и переноса схем — в OpenSpec WP-01.

1. **Модели и миграция.** ORM-классы наследуют `app.db.base.Base`; модели импортируются для metadata
   в `migrations/env.py`. Новую ревизию создают после текущего head через `just migration "описание"`
   или `just test-db-migration "описание"`; ограничения и индексы проверяют вручную.
2. **Предметный роутер.** `app.include_router(...)` в `src/app/main.py`; Pydantic-схемы размещаются
   в `src/app/schemas/`. Для предметных ошибок запланирована иерархия ServiceError и преобразование
   в контрактные ответы через `src/app/errors.py`; существующий ApiError сохраняется.
3. **Брокер.** Издатель событий по `asyncapi.yaml` и реализация `BrokerProbe.ping` для readiness;
   подставляется в `build_context`. Брокер стартует параллельно с `app`, поэтому подключение должно
   переживать его временную недоступность (повтор или ленивое соединение).
4. **Фоновые задачи.** `context.jobs.register("<имя>", корутина)`; при `TEST_MODE=0` реестр крутится с
   интервалом `JOBS_INTERVAL_SECONDS`, при `TEST_MODE=1` — только `POST /__test/jobs/<имя>/run`.
5. **Seed и сброс.** `app.maintenance.seed.load_seed` выполняет прямые идемпотентные INSERT.
   Подключённый `context.reset_state` вызывает `app.maintenance.reset.restore_seed`
   (очистка таблиц + загрузка seed) в одном session_scope для `POST /__test/reset`.
6. **Клиент заглушки.** `lifespan` управляет общим экземпляром HTTPX. Сценарии проверки занятий
   получают `context.people_client` через явный параметр и вызывают `collect_lesson_reference_data`.
   Сервис параллельно собирает данные, а `errors.py` формирует контрактные ответы 422/502/504.

## Выбор брокера

Проверка запускает стек командой `docker compose up --build` без `.env`, поэтому выбор брокера
фиксируется в `docker-compose.yml`. По умолчанию поднимается RabbitMQ. Для Kafka:

1. в блоке `x-app-env` замените значения по умолчанию: `BROKER` → `kafka`, `BROKER_URL` → `kafka:9092`;
2. перенесите профиль: у сервиса `kafka` удалите `profiles: ["kafka"]`, сервису `rabbitmq` добавьте
   `profiles: ["rabbitmq"]`.

Код читает только `BROKER` и `BROKER_URL`. E2e определяют брокер сами по открытому порту
(5672 — RabbitMQ, 9092 — Kafka); если подняты оба, задайте `BROKER`.

## Соглашения, которые уже заложены

- `datetime.now()` — только внутри `src/app/clock.py`; везде иначе — `Clock` из контекста.
- Время в ответах и событиях — `to_iso_z` (UTC, суффикс `Z`, без микросекунд).
- 400 `BAD_REQUEST` — невалидный JSON или неверный тип поля; 422 `VALIDATION_ERROR` с `details.fields` —
  неверное значение (в т. ч. время без смещения); правила классификации — `src/app/errors.py`.
  Это решение каркаса; его можно уточнить, описав в README («Решения»).
- `/__test/*` при `TEST_MODE=0` отвечают 404 `NOT_FOUND` в едином формате.

## Если выбран Sanic

Каркас HTTP-слоя написан на FastAPI: `src/app/main.py`, `src/app/api/*`, `src/app/errors.py`,
`src/app/context.py`. Остальное (`settings`, `db`, `clock`, `jobs`, `seed`, `migrations/`, Docker,
compose, justfile, e2e) от фреймворка не зависит. При переходе на Sanic замените перечисленные модули
и зависимости `fastapi`/`uvicorn` в `pyproject.toml`; поведение `/health/*` и `/__test/*` должно
остаться прежним.

## Как устроены e2e

- Запуск: `just up`, затем `just e2e-public`. Адреса по умолчанию — `localhost:8000` (сервис),
  `localhost:8100` (заглушка), брокер — по открытому порту; переопределение — переменные из
  `.env.example` (`E2E_BASE_URL`, `E2E_STUB_URL`, `BROKER`, `E2E_BROKER_URL`).
- Перед каждым сценарием фикстура `clean_state` выполняет `PUT /__test/time` (время из
  `tests/e2e/assignment.py`), `POST /__test/reset`, `DELETE /__stub/config`, `DELETE /__stub/stats`
  и очищает очередь/топик брокера.
- Отчёт `e2e-report.json`: `id`, `scenario`, `must`, `expected`, `actual`, `contract_violation`;
  `contract_violation` выставляется, когда ответ не соответствует схеме из `openapi.yaml`
  (проверка через `tests/e2e/contract.py`).
- Скрытый набор проверяющих использует те же хелперы и то же окружение.
