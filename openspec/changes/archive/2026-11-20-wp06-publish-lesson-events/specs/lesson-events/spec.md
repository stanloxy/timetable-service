## ADDED Requirements

### Requirement: Publish committed lesson transitions
Система SHALL отправлять `LessonConfirmed`, `LessonCancelled` и `LessonRescheduled` непосредственно после успешного commit соответствующего перехода (FR-13). Отклонённый переход или rollback SHALL завершаться без вызова издателя. При переносе публикация SHALL следовать за фиксацией исходного занятия и преемника в одной транзакции.

#### Scenario: Publish after commit
- **WHEN** подтверждение, отмена или перенос завершается успешным commit
- **THEN** на момент вызова издателя другое соединение PostgreSQL видит сохранённый результат перехода
- **AND** при переносе доступны обе записи, исходное занятие в `RESCHEDULED` и преемник в `PLANNED`

#### Scenario: Reject a repeated confirmation
- **WHEN** успешное подтверждение вернуло `200` и подписанная очередь получила одно событие, после чего клиент повторяет подтверждение
- **THEN** повтор возвращает `409 TRANSITION_FORBIDDEN` с `current_status: CONFIRMED` и `target_status: CONFIRMED`
- **AND** очередь не получает второго события

#### Scenario: Skip publication on rejection or rollback
- **WHEN** переход отклонён или ошибка при записи либо commit вызывает rollback
- **THEN** издатель не вызывается
- **AND** при переносе исходная запись сохраняется, а преемник отсутствует

### Requirement: Use the AsyncAPI event contract
Система SHALL строить JSON-события по `asyncapi.yaml` и публиковать их в долговечный topic exchange `wa.events` по ключу `timetable.<EventType>`. Сообщение SHALL иметь `content_type=application/json`, `message_id=event_id` и `delivery_mode=2`. Конверт SHALL содержать UUID `event_id`, `event_type`, `occurred_at` по `Clock` на момент перехода в UTC с `Z`, `idempotency_key` в формате `<event-type-kebab>:<lesson_id>`, `producer: timetable-service`, `version: 1` и `payload`.

#### Scenario: Encode a confirmation
- **WHEN** подтверждено занятие
- **THEN** payload содержит ID занятия, группы и преподавателя, `classroom_id` включая `null`, `format`, `starts_at` и `ends_at`

#### Scenario: Encode a cancellation
- **WHEN** отменено запланированное или подтверждённое занятие
- **THEN** payload содержит ID занятия, группы и преподавателя, даты интервала, `previous_status` до отмены и обязательное поле `reason`, в том числе `null`

#### Scenario: Encode both sides of a reschedule
- **WHEN** занятие перенесено со сменой преподавателя и явным очищением аудитории
- **THEN** `payload.lesson_id` и ключ идемпотентности используют ID исходного занятия, `rescheduled_to_id` использует ID преемника, а `group_id` общий для обеих записей
- **AND** верхнеуровневый `instructor_id` относится к исходному занятию
- **AND** `previous` и `new` содержат даты, преподавателя и обязательное поле `classroom_id` каждого интервала, в новом интервале аудитория равна `null`

### Requirement: Bound publication and preserve the committed HTTP result
Система SHALL использовать общий лимит в две секунды для подготовки и подтверждения публикации. Временный сбой до вызова `publish` MAY повторить подготовку, всего не более трёх попыток. Для события SHALL быть не более одного вызова `publish`. Если брокер не подтвердил приём или вернул сообщение без маршрута, система SHALL один раз записать итоговый сбой и вернуть штатный успешный ответ о сохранённом переходе.

#### Scenario: Recover before sending
- **WHEN** временный сбой соединения или открытия канала происходит до вызова `publish`
- **THEN** подготовка может повториться в пределах общего лимита, всего не более трёх попыток
- **AND** при восстановлении брокера сообщение отправляется один раз

#### Scenario: Stop on a permanent preparation failure
- **WHEN** подготовку прерывает постоянная ошибка, например отказ в доступе
- **THEN** система завершает попытку, один раз записывает сбой и возвращает успешный ответ о сохранённом переходе

#### Scenario: Preserve the write when publisher confirmation is missing
- **WHEN** после вызова `publish` истекает время ожидания подтверждения или обрывается соединение
- **THEN** отправка того же события не повторяется, неизвестный результат записывается в журнал один раз
- **AND** HTTP-ответ остаётся `200` для подтверждения и отмены либо `201` для переноса
- **AND** изменения остаются видимыми в PostgreSQL
