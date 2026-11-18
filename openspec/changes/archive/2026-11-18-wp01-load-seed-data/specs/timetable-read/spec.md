# Spec Delta

## Purpose

Обеспечить чтение сохранённых групп и занятий по идентификатору с ответами по нормативному контракту API (FR-04, FR-11).

## ADDED Requirements

### Requirement: Read a group by identifier
Система SHALL обрабатывать `GET /groups/{group_id}` для существующей группы ответом `200` с объектом `Group` непосредственно в теле, содержащим `id`, `name`, `size` по `openapi.yaml` (FR-11).

#### Scenario: Read a seeded group
- **WHEN** после загрузки seed выполняется `GET /groups/9a000000-0000-4000-8000-000000000001`
- **THEN** ответ имеет статус `200` и соответствует схеме `Group`
- **AND** тело содержит `id = 9a000000-0000-4000-8000-000000000001`, `name = ПРГ-24-1`, `size = 12`

### Requirement: Read a lesson by identifier
Система SHALL обрабатывать `GET /lessons/{lesson_id}` для существующего занятия ответом `200` с объектом `Lesson` непосредственно в теле по `openapi.yaml`. Все обязательные поля SHALL присутствовать, включая поля со значением `null` (FR-04).

#### Scenario: Read a seeded lesson
- **WHEN** после загрузки seed выполняется `GET /lessons/3d000000-0000-4000-8000-000000000001`
- **THEN** ответ имеет статус `200` и соответствует схеме `Lesson`
- **AND** значения обязательных полей совпадают с записью L1 в seed
- **AND** `rescheduled_from_id` и `cancel_reason` присутствуют со значением `null`

#### Scenario: Read an online lesson
- **WHEN** после загрузки seed читается занятие L3 по идентификатору
- **THEN** ответ имеет статус `200`, `format = ONLINE` и `classroom_id = null`

#### Scenario: Read a reschedule successor
- **WHEN** после загрузки seed читается занятие L7 по идентификатору
- **THEN** ответ имеет статус `200`
- **AND** `rescheduled_from_id` содержит идентификатор L6

### Requirement: Missing resource response
Система SHALL отвечать на чтение отсутствующей группы или занятия статусом `404` и кодом `NOT_FOUND` в формате `{"error": {"code", "message", "details"}}`, где `message` — строка, а `details` — объект.

#### Scenario: Read an absent group
- **WHEN** выполняется `GET /groups/9a000000-0000-4000-8000-000000000099` и такая группа отсутствует
- **THEN** ответ имеет статус `404`, соответствует схеме `Error` и содержит `error.code = NOT_FOUND`

#### Scenario: Read an absent lesson
- **WHEN** выполняется `GET /lessons/3d000000-0000-4000-8000-000000000099` и такое занятие отсутствует
- **THEN** ответ имеет статус `404`, соответствует схеме `Error` и содержит `error.code = NOT_FOUND`

### Requirement: UTC lesson timestamps
Система SHALL возвращать временные поля занятия `starts_at`, `ends_at`, `created_at`, `updated_at` в формате ISO 8601 UTC с суффиксом `Z` по `openapi.yaml`.

#### Scenario: Serialize lesson timestamps
- **WHEN** читается существующее занятие
- **THEN** каждое из четырёх временных полей обозначает сохранённый момент времени в UTC и заканчивается на `Z`

### Requirement: Read independence from people-stub
Система SHALL читать группы и занятия из сохранённых данных без обращений к people-stub и без изменения предметных данных.

#### Scenario: Read while people-stub is unavailable
- **WHEN** при недоступном people-stub читаются существующие группа и занятие
- **THEN** оба запроса возвращают `200` без запросов к people-stub
- **AND** сохранённые предметные данные не изменяются
