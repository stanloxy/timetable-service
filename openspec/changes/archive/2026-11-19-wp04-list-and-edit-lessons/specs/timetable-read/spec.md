## ADDED Requirements

### Requirement: Filter the lesson list
Система SHALL обрабатывать `GET /lessons` по FR-03. Фильтры `group_id`, `instructor_id`, `classroom_id`, `status`, `from` и `to` SHALL объединяться по И. Период SHALL применяться к `starts_at` с включением нижней и исключением верхней границы. Чтение SHALL работать без people-stub и изменений данных.

#### Scenario: Combine filters and check both time boundaries
- **WHEN** запрос содержит фильтры по группе, преподавателю, аудитории, статусу и периоду
- **THEN** в ответе только занятия, удовлетворяющие всем переданным фильтрам
- **AND** совпадающее занятие с началом ровно в `from` включается, с началом ровно в `to` исключается
- **AND** занятие, начавшееся до `from` и продолжающееся внутри периода, исключается

#### Scenario: Filter by one boundary or return no matches
- **WHEN** передана только одна граница
- **THEN** применяется только соответствующее условие к `starts_at`
- **AND** для равных или обратных границ, а также для корректного UUID без совпадений ответ содержит `items: []` и `total: 0`

#### Scenario: Reject invalid query parameters
- **WHEN** UUID v4, статус, дата, смещение даты, `limit` или `offset` не проходят входную проверку
- **THEN** ответ имеет статус `422 VALIDATION_ERROR`, а `details.fields` содержит имя параметра

#### Scenario: Read a page with people-stub unavailable
- **WHEN** people-stub недоступен, а параметры запроса корректны
- **THEN** список возвращается из БД с кодом `200` без вызовов people-stub и изменений расписания

### Requirement: Paginate lessons with a stable order and total
Система SHALL возвращать `200 {items, total}` по `openapi.yaml`. Страница SHALL сортироваться по возрастанию `starts_at`, затем `id`. `limit` SHALL быть от 1 до 200, по умолчанию 50. `offset` SHALL быть от 0, по умолчанию 0. `total` SHALL содержать число совпадений до пагинации по тому же состоянию данных, из которого получены `items`.

#### Scenario: Sort tied starts and count an empty page
- **WHEN** совпадения имеют одинаковые начала и запрашиваются несколько страниц, включая смещение за концом выборки
- **THEN** занятия с одинаковым началом идут по возрастанию ID
- **AND** все страницы возвращают число совпадений до пагинации при неизменных данных, включая пустую страницу
