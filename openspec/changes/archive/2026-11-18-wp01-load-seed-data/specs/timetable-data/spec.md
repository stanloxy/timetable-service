# Spec Delta

## Purpose

Обеспечить хранение групп и занятий с ограничениями целостности данных и воспроизводимой схемой БД.

## ADDED Requirements

### Requirement: Positive group size
Система SHALL разрешать сохранение группы только с размером больше нуля.

#### Scenario: Reject zero group size
- **WHEN** выполняется попытка сохранить группу с `size = 0`
- **THEN** запись отклоняется с ошибкой ограничения целостности
- **AND** группа не сохраняется

#### Scenario: Accept minimum group size
- **WHEN** сохраняется группа с `size = 1` и корректными остальными полями
- **THEN** группа сохраняется без ошибки

#### Scenario: Reject negative group size
- **WHEN** сохраняется группа с `size = -1` и корректными остальными полями
- **THEN** запись отклоняется с ошибкой ограничения целостности и группа не сохраняется

### Requirement: Lesson duration bounds
Система SHALL разрешать сохранение занятия только с длительностью от 30 минут до 8 часов включительно (BR-01).

#### Scenario: Reject lesson shorter than minimum
- **WHEN** сохраняется занятие длительностью 29 минут с корректными остальными полями
- **THEN** запись отклоняется с ошибкой ограничения целостности
- **AND** занятие не сохраняется

#### Scenario: Accept minimum lesson duration
- **WHEN** сохраняется занятие длительностью ровно 30 минут с корректными остальными полями
- **THEN** занятие сохраняется без ошибки

#### Scenario: Accept maximum lesson duration
- **WHEN** сохраняется занятие длительностью ровно 8 часов с корректными остальными полями
- **THEN** занятие сохраняется без ошибки

#### Scenario: Reject lesson longer than maximum
- **WHEN** сохраняется занятие длительностью 8 часов 1 минута с корректными остальными полями
- **THEN** запись отклоняется с ошибкой ограничения целостности
- **AND** занятие не сохраняется

### Requirement: Lesson format and classroom consistency
Система SHALL разрешать сохранение занятия формата `ONLINE` только с `classroom_id = NULL`, а формата `IN_PERSON` — только с указанным `classroom_id` (BR-02).

#### Scenario: Accept online lesson without classroom
- **WHEN** сохраняется занятие формата `ONLINE` с `classroom_id = NULL` и корректными остальными полями
- **THEN** занятие сохраняется без ошибки

#### Scenario: Reject online lesson with classroom
- **WHEN** сохраняется занятие формата `ONLINE` с указанным `classroom_id` и корректными остальными полями
- **THEN** запись отклоняется с ошибкой ограничения целостности
- **AND** занятие не сохраняется

#### Scenario: Accept in-person lesson with classroom
- **WHEN** сохраняется занятие формата `IN_PERSON` с указанным `classroom_id` и корректными остальными полями
- **THEN** занятие сохраняется без ошибки

#### Scenario: Reject in-person lesson without classroom
- **WHEN** сохраняется занятие формата `IN_PERSON` с `classroom_id = NULL` и корректными остальными полями
- **THEN** запись отклоняется с ошибкой ограничения целостности
- **AND** занятие не сохраняется

### Requirement: Unique required identifiers
Система SHALL хранить обязательный уникальный UUID `id` для каждой группы и каждого занятия. Уникальность SHALL обеспечиваться отдельно в каждой таблице.

#### Scenario: Accept a new identifier
- **WHEN** сохраняется группа или занятие с новым UUID и корректными остальными полями
- **THEN** запись сохраняется без ошибки

#### Scenario: Reject a duplicate identifier
- **WHEN** сохраняется новая группа или новое занятие с UUID, уже занятым другой строкой той же таблицы
- **THEN** запись отклоняется с ошибкой ограничения целостности и новая строка не сохраняется

#### Scenario: Reject a null identifier
- **WHEN** сохраняется группа или занятие с `id = NULL`
- **THEN** запись отклоняется с ошибкой ограничения целостности и строка не сохраняется

### Requirement: Required group fields
Система SHALL запрещать `NULL` в полях группы `name` и `size`.

#### Scenario: Reject a null required group field
- **WHEN** сохраняется группа с `NULL` в одном из полей `name` или `size` и корректными остальными полями; проверка выполняется отдельно для каждого поля
- **THEN** запись отклоняется с ошибкой ограничения целостности и группа не сохраняется

### Requirement: Required lesson fields
Система SHALL запрещать `NULL` в полях занятия `group_id`, `instructor_id`, `status`, `format`, `starts_at`, `ends_at`, `created_at`, `updated_at`.

#### Scenario: Reject a null required lesson field
- **WHEN** сохраняется занятие с `NULL` в одном из обязательных полей и корректными остальными полями; проверка выполняется отдельно для каждого поля
- **THEN** запись отклоняется с ошибкой ограничения целостности и занятие не сохраняется

### Requirement: Nullable lesson fields
Система SHALL допускать `NULL` в полях занятия `classroom_id`, `rescheduled_from_id`, `cancel_reason` при соблюдении остальных ограничений, включая соответствие формата аудитории.

#### Scenario: Accept absent optional values
- **WHEN** сохраняется корректное занятие `ONLINE` с `classroom_id = NULL`, `rescheduled_from_id = NULL` и `cancel_reason = NULL`
- **THEN** занятие сохраняется без ошибки

#### Scenario: Accept cancellation without a reason
- **WHEN** сохраняется корректное занятие в статусе `CANCELLED` с `cancel_reason = NULL`
- **THEN** занятие сохраняется без ошибки

### Requirement: Existing lesson group
Система SHALL разрешать сохранение занятия только со ссылкой `group_id` на существующую группу (BR-03).

#### Scenario: Accept an existing group
- **WHEN** сохраняется занятие со ссылкой на существующую группу и корректными остальными полями
- **THEN** занятие сохраняется без ошибки

#### Scenario: Reject an absent group
- **WHEN** сохраняется занятие с `group_id`, отсутствующим среди групп
- **THEN** запись отклоняется с ошибкой ограничения целостности и занятие не сохраняется

### Requirement: Allowed lesson statuses
Система SHALL разрешать только статусы `PLANNED`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`, `RESCHEDULED`.

#### Scenario: Accept each allowed status
- **WHEN** сохраняется занятие с одним из допустимых статусов и корректными остальными полями; проверка выполняется для каждого допустимого статуса
- **THEN** занятие сохраняется без ошибки

#### Scenario: Reject an unknown status
- **WHEN** сохраняется занятие со статусом `UNKNOWN` и корректными остальными полями
- **THEN** значение отклоняется и занятие не сохраняется

### Requirement: Allowed lesson formats
Система SHALL разрешать только форматы `IN_PERSON` и `ONLINE`.

#### Scenario: Accept each allowed format
- **WHEN** сохраняется занятие с одним из допустимых форматов, соответствующей ему аудиторией и корректными остальными полями
- **THEN** занятие сохраняется без ошибки

#### Scenario: Reject an unknown format
- **WHEN** сохраняется занятие с форматом `UNKNOWN` и корректными остальными полями
- **THEN** значение отклоняется и занятие не сохраняется

### Requirement: Positive lesson interval
Система SHALL отклонять занятия, у которых `ends_at` не позже `starts_at` (BR-01).

#### Scenario: Reject zero duration
- **WHEN** сохраняется занятие с `ends_at = starts_at` и корректными остальными полями
- **THEN** запись отклоняется с ошибкой ограничения целостности и занятие не сохраняется

#### Scenario: Reject negative duration
- **WHEN** сохраняется занятие с `ends_at` раньше `starts_at` и корректными остальными полями
- **THEN** запись отклоняется с ошибкой ограничения целостности и занятие не сохраняется

### Requirement: Existing reschedule predecessor
Система SHALL допускать ненулевой `rescheduled_from_id` только при наличии исходного занятия с таким `id`.

#### Scenario: Accept an existing predecessor
- **WHEN** сохраняется корректное новое занятие со ссылкой на существующее исходное занятие, у которого ещё нет преемника
- **THEN** новое занятие сохраняется без ошибки

#### Scenario: Reject an absent predecessor
- **WHEN** сохраняется занятие с `rescheduled_from_id`, отсутствующим среди занятий
- **THEN** запись отклоняется с ошибкой ограничения целостности и занятие не сохраняется

### Requirement: At most one reschedule successor
Система SHALL запрещать нескольким занятиям ссылаться на один ненулевой `rescheduled_from_id`, в том числе при одновременной записи.

#### Scenario: Reject a second successor
- **WHEN** сохраняется второе занятие со ссылкой на исходное занятие, у которого уже есть преемник
- **THEN** запись отклоняется с ошибкой ограничения целостности
- **AND** ранее сохранённый преемник остаётся единственным

#### Scenario: Allow multiple lessons without predecessors
- **WHEN** сохраняются несколько корректных занятий с `rescheduled_from_id = NULL`
- **THEN** все занятия сохраняются без ошибки

#### Scenario: Reject concurrent duplicate successors
- **WHEN** две транзакции пытаются сохранить разных преемников одного исходного занятия и зафиксировать обе записи
- **THEN** успешно фиксируется только один преемник
- **AND** другая запись отклоняется с ошибкой ограничения целостности

### Requirement: No self-reference on reschedule
Система SHALL запрещать занятию ссылаться на себя через `rescheduled_from_id`.

#### Scenario: Reject a self-reference
- **WHEN** сохраняется занятие с `rescheduled_from_id = id`
- **THEN** запись отклоняется с ошибкой ограничения целостности и занятие не сохраняется

### Requirement: Protect referenced groups
Система SHALL запрещать удаление группы, на которую ссылается хотя бы одно занятие.

#### Scenario: Reject deleting a referenced group
- **WHEN** удаляется группа, на которую ссылается существующее занятие
- **THEN** удаление отклоняется с ошибкой ограничения целостности
- **AND** группа и занятие сохраняются

### Requirement: Protect reschedule history
Система SHALL запрещать удаление исходного занятия, на которое ссылается преемник.

#### Scenario: Reject deleting a referenced predecessor
- **WHEN** удаляется исходное занятие с существующим преемником
- **THEN** удаление отклоняется с ошибкой ограничения целостности
- **AND** исходное занятие и ссылка преемника сохраняются

### Requirement: External resource references
Система SHALL хранить идентификаторы преподавателей и аудиторий без требования их наличия в локальных таблицах. Проверка существования этих ресурсов в people-stub не является ограничением локального хранения.

#### Scenario: Store seed without local external resources
- **WHEN** напрямую сохраняются корректные seed-занятия с идентификаторами преподавателей и аудиторий
- **THEN** записи сохраняются без локальных строк преподавателей и аудиторий
- **AND** запросы к people-stub не выполняются

### Requirement: Past lesson dates
Система SHALL допускать хранение занятий с интервалом в прошлом при соблюдении остальных ограничений.

#### Scenario: Accept a past lesson
- **WHEN** сохраняется корректное занятие, у которого начало и конец раньше текущего времени сервиса
- **THEN** занятие сохраняется без ошибки

### Requirement: Reproducible schema migrations
Система SHALL создавать предметную схему применением всей цепочки миграций Alembic к пустой БД (NFR-02).

#### Scenario: Migrate an empty database
- **WHEN** вся цепочка миграций применяется к пустой БД
- **THEN** создаётся схема групп и занятий с указанными ограничениями
- **AND** схема позволяет сохранить все записи из выданных файлов seed
