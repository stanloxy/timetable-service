## ADDED Requirements

### Requirement: Check lesson status before transition
Система SHALL проверять существование занятия и актуальный статус под блокировкой строки перед HTTP-переходом. Для корректного запроса к отсутствующему занятию система SHALL вернуть `404 NOT_FOUND`. Недопустимый переход SHALL вернуть `409 TRANSITION_FORBIDDEN` с `details.current_status` и `details.target_status`. Проверка статуса SHALL предшествовать предметным проверкам BR-01…BR-07 и BR-08. Успешный HTTP-переход SHALL записать `updated_at` из `Clock` и вернуть ответ после успешного commit.

#### Scenario: Reject a missing lesson
- **WHEN** клиент направляет корректный запрос любого из четырёх переходов для отсутствующего занятия
- **THEN** система возвращает `404 NOT_FOUND`

#### Scenario: Reject a reschedule before checking the candidate
- **WHEN** клиент переносит занятие в недопустимом статусе и корректно сформированное тело нарушило бы правила расписания
- **THEN** система возвращает `409 TRANSITION_FORBIDDEN` с текущим статусом и `target_status: RESCHEDULED`
- **AND** обращения к people-stub отсутствуют, а расписание сохраняется

### Requirement: Confirm a planned lesson
Система SHALL обрабатывать `POST /lessons/{lesson_id}/confirm` (FR-06) переходом `PLANNED → CONFIRMED` и возвращать `200` с объектом `Lesson`.

#### Scenario: Confirm once
- **WHEN** клиент подтверждает занятие в `PLANNED`
- **THEN** ответ `200` содержит это занятие со статусом `CONFIRMED`
- **AND** повторное подтверждение возвращает `409 TRANSITION_FORBIDDEN` с `current_status: CONFIRMED` и `target_status: CONFIRMED`

### Requirement: Cancel a planned or confirmed lesson
Система SHALL обрабатывать `POST /lessons/{lesson_id}/cancel` (FR-07) переходом из `PLANNED` или `CONFIRMED` в `CANCELLED` и возвращать `200` с объектом `Lesson`. Тело SHALL быть необязательным. Если оно передано, оно SHALL быть объектом `CancelRequest`. Поле `reason` SHALL допускать строку длиной до 500 символов или `null` и сохраняться в `cancel_reason`.

#### Scenario: Cancel with an optional reason
- **WHEN** клиент отменяет `PLANNED` или `CONFIRMED` с допустимой строкой `reason`
- **THEN** ответ `200` содержит статус `CANCELLED` и переданную строку в `cancel_reason`
- **AND** запрос без тела, с пустым объектом или `reason: null` сохраняет `cancel_reason: null`

#### Scenario: Reject an invalid cancellation body
- **WHEN** тело содержит невалидный JSON, JSON `null` вместо объекта или неверный тип причины
- **THEN** система возвращает `400 BAD_REQUEST`
- **AND** строка свыше 500 символов или лишнее поле дают `422 VALIDATION_ERROR` с полем ошибки в `details.fields`

### Requirement: Reschedule a lesson atomically
По FR-08 `POST /lessons/{lesson_id}/reschedule` SHALL переводить исходное занятие из `PLANNED` или `CONFIRMED` в `RESCHEDULED` и создавать одного преемника в `PLANNED` с той же группой и ссылкой `rescheduled_from_id`. Обе записи SHALL фиксироваться одной транзакцией. Для кандидата SHALL применяться BR-01…BR-07 с исключением исходного из BR-05 и BR-06. Ответ `201 {lesson, warnings}` SHALL содержать преемника и предупреждения.

#### Scenario: Inherit omitted fields and clear the classroom explicitly
- **WHEN** клиент переносит очное занятие, передаёт обязательные `starts_at` и `ends_at` и пропускает преподавателя, аудиторию и формат
- **THEN** преемник наследует эти три поля
- **AND** при переносе очного занятия с `format: ONLINE` и явным `classroom_id: null` преемник сохраняется без аудитории
- **AND** при смене формата на `ONLINE` с пропущенной аудиторией срабатывает BR-02

#### Scenario: Count the candidate once
- **WHEN** новый интервал пересекает только исходное занятие, а лимит дневной нагрузки допускает кандидата при исключении исходного
- **THEN** исходное занятие не вызывает конфликт и не добавляет предупреждение о нагрузке
- **AND** нарушения мягких правил самим кандидатом возвращаются в `warnings`

#### Scenario: Preserve the original on a failure
- **WHEN** расписание или people-stub отклоняет перенос либо транзакция завершается ошибкой
- **THEN** в БД сохраняется прежняя исходная запись, включая её статус и `updated_at`
- **AND** преемник отсутствует

#### Scenario: Allow only one successor
- **WHEN** два запроса переносят одно исходное занятие и первый фиксирует перенос
- **THEN** в БД есть ровно один преемник
- **AND** второй запрос возвращает `409 TRANSITION_FORBIDDEN` с `current_status: RESCHEDULED` и `target_status: RESCHEDULED`
- **AND** последующий повторный перенос того же исходного занятия возвращает тот же отказ

### Requirement: Complete a finished lesson
Система SHALL обрабатывать `POST /lessons/{lesson_id}/complete` (FR-09). Переход `IN_PROGRESS → COMPLETED` SHALL быть допустим при `Clock.now() >= ends_at` (BR-08). Успех SHALL возвращать `200` с объектом `Lesson`.

#### Scenario: Reject completion before the end
- **WHEN** занятие в `IN_PROGRESS` и `Clock.now() < ends_at`
- **THEN** система возвращает `409 LESSON_NOT_FINISHED` с `details.ends_at` и `details.now` в UTC с суффиксом `Z`
- **AND** занятие сохраняет прежний статус и `updated_at`

#### Scenario: Complete at the exact boundary
- **WHEN** занятие в `IN_PROGRESS` и `Clock.now() == ends_at`
- **THEN** ответ `200` содержит занятие в `COMPLETED`

#### Scenario: Check status before the time rule
- **WHEN** занятие в статусе, отличном от `IN_PROGRESS`, а `ends_at` ещё не наступил
- **THEN** система возвращает `409 TRANSITION_FORBIDDEN` с `target_status: COMPLETED`

### Requirement: Start due confirmed lessons
Задача `lesson-status-sweeper` (FR-10) SHALL переводить только `CONFIRMED` со `starts_at <= Clock.now()` в `IN_PROGRESS`, в том числе после `ends_at`. Задача SHALL использовать один снимок времени для отбора и обновления `updated_at` и возвращать число фактически переведённых занятий после commit.

#### Scenario: Sweep due lessons exactly once
- **WHEN** задача выполняется при наличии подтверждённых занятий с началом ровно сейчас и с уже прошедшим окончанием, а также будущего подтверждённого занятия и занятий других статусов
- **THEN** переводятся только подходящие подтверждённые занятия, и подсчёт равен числу этих переходов
- **AND** повторный запуск с тем же временем и без других изменений возвращает ноль

#### Scenario: Serialize a sweep with cancellation or reschedule
- **WHEN** sweeper и отмена или перенос конкурируют за подходящее подтверждённое занятие
- **THEN** при первом commit отмены или переноса sweeper пропускает исходную строку
- **AND** при первом commit sweeper HTTP-запрос отклоняется с `409 TRANSITION_FORBIDDEN` и `current_status: IN_PROGRESS`

### Requirement: Run the sweeper in the configured mode
При `TEST_MODE=1` система SHALL выполнять `lesson-status-sweeper` через `POST /__test/jobs/lesson-status-sweeper/run` с ответом `200 {"processed": <int>}`. Неизвестное имя SHALL давать `404 NOT_FOUND`. При `TEST_MODE=0` система SHALL вызывать задачу через существующий периодический цикл с `JOBS_INTERVAL_SECONDS`, по умолчанию 30 секунд и максимум 60 секунд. Тестовый маршрут SHALL возвращать `404 NOT_FOUND`.

#### Scenario: Run manually in test mode
- **WHEN** включён `TEST_MODE`, время зафиксировано и запускается ручной sweeper
- **THEN** задача синхронно возвращает число переходов, а периодический цикл отключён
- **AND** ручной вызов неизвестного имени возвращает `404 NOT_FOUND`

#### Scenario: Run periodically outside test mode
- **WHEN** приложение работает с выключенным `TEST_MODE`
- **THEN** существующий цикл вызывает зарегистрированный sweeper с настроенным интервалом
- **AND** ручной вызов через тестовый маршрут возвращает `404 NOT_FOUND`
