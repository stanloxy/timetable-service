# lesson-scheduling Specification

## Purpose
Создавать и предварительно проверять занятия по правилам расписания (FR-01, FR-02). Сервис возвращает точные пересечения и предупреждения, а создание через API защищено от конкурирующих записей по общим ресурсам.

## Requirements

### Requirement: Create a planned lesson
Система SHALL обрабатывать `POST /lessons` по BR-01…BR-07 и после успешной фиксации возвращать `201 {lesson, warnings}` по `openapi.yaml` (FR-01). Запись SHALL иметь UUID v4, статус `PLANNED`, `rescheduled_from_id = null`, `cancel_reason = null` и одинаковые значения `created_at` и `updated_at` из `Clock`. Система SHALL возвращать время занятия в UTC с суффиксом `Z`, сохраняя дробные секунды. Допустимы и прошедшие интервалы. Создание SHALL выполняться без событий.

#### Scenario: Create and read a lesson
- **WHEN** передано корректное занятие без пересечений и предупреждений, в том числе с прошедшим интервалом
- **THEN** ответ имеет статус `201`, содержит полностью заполненный `Lesson` с указанными значениями и `warnings: []`
- **AND** последующий `GET /lessons/{lesson_id}` возвращает то же занятие

### Requirement: Evaluate hard rules in order
Для обоих POST-маршрутов система SHALL проверять BR-01, BR-02 и существование группы до вызовов people-stub. После получения справочных данных SHALL проверять BR-04 перед BR-05. Первый hard-отказ SHALL завершать проверку. Ошибки запроса и предметные отказы SHALL соответствовать кодам и формату `openapi.yaml`.

#### Scenario: Reject malformed requests at the HTTP boundary
- **WHEN** передан некорректный JSON или значение поля неправильного JSON-типа
- **THEN** ответ имеет статус `400 BAD_REQUEST`
- **AND** предметные проверки и вызовы people-stub не выполняются

#### Scenario: Reject a missing offset on either endpoint
- **WHEN** корректная строка даты и времени передана без смещения
- **THEN** ответ имеет статус `422 VALIDATION_ERROR`
- **AND** `details.fields` указывает поле даты и времени

#### Scenario: Reject an invalid interval before format and references
- **WHEN** окончание не позже начала или длительность выходит за диапазон от 30 минут до 8 часов, а формат и ссылки также нарушают правила
- **THEN** ответ имеет статус `422 VALIDATION_ERROR` с `details.fields.ends_at`
- **AND** people-stub не вызывается

#### Scenario: Accept interval limits
- **WHEN** длительность равна ровно 30 минутам или ровно 8 часам и остальные hard-правила соблюдены
- **THEN** BR-01 проходит для обоих маршрутов

#### Scenario: Reject an invalid classroom and format combination before references
- **WHEN** интервал корректен, а `IN_PERSON` передан без аудитории либо `ONLINE` передан с аудиторией
- **THEN** ответ имеет статус `422 CLASSROOM_REQUIRED` с пустым `details` для первого случая либо `422 VALIDATION_ERROR` с `details.fields.classroom_id` для второго
- **AND** people-stub не вызывается

#### Scenario: Check the local group before people-stub
- **WHEN** интервал и формат корректны, а группы нет
- **THEN** ответ имеет статус `422 GROUP_NOT_FOUND` с `details.group_id`
- **AND** people-stub не вызывается

#### Scenario: Preserve reference data failure priority
- **WHEN** интервал, формат и группа корректны, а один или несколько необходимых вызовов people-stub завершаются ожидаемым отказом
- **THEN** оба маршрута возвращают первую применимую ошибку в порядке `504 UPSTREAM_TIMEOUT`, `502 UPSTREAM_UNAVAILABLE`, `422 INSTRUCTOR_NOT_FOUND`, `422 CLASSROOM_NOT_FOUND`
- **AND** `details` содержит соответственно `upstream` и `timeout_ms`, только `upstream`, только `instructor_id` или только `classroom_id`
- **AND** расписание не меняется

#### Scenario: Check capacity before overlap
- **WHEN** вместимость указанной аудитории меньше размера группы и одновременно есть пересечение
- **THEN** создание возвращает `409 CLASSROOM_TOO_SMALL`, а проверка возвращает `200` с единственным нарушением `CLASSROOM_TOO_SMALL`
- **AND** `details` нарушения содержит только `capacity` и `group_size`

### Requirement: Report all active lesson conflicts
При пересечении с активным занятием по общему преподавателю, аудитории или группе создание SHALL вернуть `409 SCHEDULE_CONFLICT` (BR-05). Активные статусы — `PLANNED`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`. В `details.conflicts` SHALL входить все пары «ресурс и занятие» с полями `resource`, `lesson_id`, `overlap.starts_at`, `overlap.ends_at`. Границы SHALL точно отражать пересечение в UTC с `Z`.

#### Scenario: Report several resources and lessons
- **WHEN** кандидат пересекается с одним активным занятием по двум ресурсам и с другим активным занятием по третьему
- **THEN** один отказ `SCHEDULE_CONFLICT` содержит все три пары
- **AND** для каждой пары начало равно более позднему началу, конец — более раннему окончанию, включая дробные секунды
- **AND** расписание не меняется

#### Scenario: Allow touching intervals and ignore inactive lessons
- **WHEN** активные занятия только смежны с кандидатом, а интервалы `CANCELLED` и `RESCHEDULED` пересекаются с ним
- **THEN** BR-05 проходит

#### Scenario: Compare online lessons without a classroom
- **WHEN** у онлайн-кандидата и существующего занятия нет аудитории, а преподаватель и группа различаются
- **THEN** BR-05 проходит даже при совпадающих интервалах

### Requirement: Serialize concurrent creation on shared resources
Система SHALL предотвращать фиксацию двух конкурентно создаваемых активных занятий с пересекающимися интервалами и общим ресурсом. Проверка пересечения и вставка SHALL выполняться в одной транзакции.

#### Scenario: Recheck after the competing commit
- **WHEN** два запроса на создание пересекающихся занятий с одним общим ресурсом выполняются одновременно
- **THEN** при исходно свободном интервале первый запрос сохраняет занятие и получает `201`
- **AND** второй получает `409 SCHEDULE_CONFLICT` с точным пересечением с сохранённым занятием
- **AND** среди кандидатов сохранено ровно одно занятие

#### Scenario: Recheck after the competing rollback
- **WHEN** ожидающий запрос продолжает после отката транзакции, державшей блокировку общего ресурса
- **THEN** запрос проверяет актуальное расписание и при свободном интервале сохраняет занятие

### Requirement: Validate without writing
Система SHALL обрабатывать `POST /lessons/validate` с теми же BR-01…BR-07 без сохранения занятия и событий (FR-02). Ответ SHALL сохранять HTTP-коды `400`, `422`, `502` и `504`. Нарушение BR-04 или BR-05 SHALL возвращаться при `200` одним элементом `violations` с теми же `code`, `message` и `details`, которые вернуло бы создание.

#### Scenario: Validate a hard conflict
- **WHEN** кандидат прошёл BR-01…BR-04, но пересекается с активным занятием по общему ресурсу
- **THEN** ответ имеет статус `200` с `ok: false`, единственным нарушением `SCHEDULE_CONFLICT` и `warnings: []`
- **AND** расписание не меняется

#### Scenario: Validate a lesson with only warnings
- **WHEN** кандидат проходит все hard-правила и нарушает одно или оба soft-правила
- **THEN** ответ имеет статус `200` с `ok: true`, `violations: []` и рассчитанными предупреждениями
- **AND** расписание не меняется

### Requirement: Warn about daily instructor workload
Система SHALL суммировать фактическую длительность частей активных занятий преподавателя и кандидата внутри каждого затронутого кандидатом дня в часовом поясе профиля (BR-06). За каждый день со строгим превышением лимита SHALL возвращаться `WORKLOAD_SOFT_LIMIT` с `date`, `max_hours` и `planned_hours` в порядке дат. Предупреждение SHALL допускать создание занятия.

#### Scenario: Split workload at local midnight
- **WHEN** кандидат пересекает локальную полночь и с учётом частей существующих активных занятий лимит превышен в обоих днях
- **THEN** возвращаются два предупреждения с локальными датами и длительностями, рассчитанными по пересечениям с сутками
- **AND** интервалы `CANCELLED` и `RESCHEDULED` не учитываются

#### Scenario: Allow exact daily limit
- **WHEN** суммарная длительность активных занятий с кандидатом равна дневному лимиту
- **THEN** предупреждение о нагрузке за эту дату отсутствует

### Requirement: Warn about instructor availability
Система SHALL проверять полное попадание интервала занятия в одно недельное окно в часовом поясе ответа о доступности (BR-07). При отсутствии подходящего окна SHALL возвращаться `INSTRUCTOR_UNAVAILABLE` с `details.instructor_id` после предупреждений о нагрузке. Предупреждение SHALL допускать создание занятия.

#### Scenario: Accept exact boundaries of one window
- **WHEN** занятие начинается на левой границе окна и заканчивается на правой
- **THEN** предупреждение о доступности отсутствует

#### Scenario: Warn when no single window covers the interval
- **WHEN** занятие занимает части двух смежных окон, пересекает локальную полночь или список окон пуст
- **THEN** возвращается `INSTRUCTOR_UNAVAILABLE`
- **AND** при соблюдении hard-правил создание возвращает `201` с этим предупреждением
