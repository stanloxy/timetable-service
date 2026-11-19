## ADDED Requirements

### Requirement: Edit a planned lesson
Система SHALL обрабатывать `PATCH /lessons/{lesson_id}` по FR-05. Система SHALL проверить существование занятия и статус `PLANNED` до BR-01…BR-07. Поля `LessonPatch` SHALL сливаться с текущим состоянием. Успешная правка SHALL обновлять `updated_at` из `Clock` и возвращать `200 {lesson, warnings}` после commit. Операция SHALL выполняться без публикации событий.

#### Scenario: Preserve omitted values and clear a supplied classroom
- **WHEN** корректный PATCH меняет время очного занятия и пропускает `classroom_id`
- **THEN** ответ содержит прежнюю аудиторию и обновлённое время
- **AND** последующее изменение формата на `ONLINE` с явным `classroom_id: null` очищает аудиторию
- **AND** `id`, `group_id`, `status`, `created_at`, `rescheduled_from_id` и `cancel_reason` сохраняются, а `updated_at` берётся из `Clock`

#### Scenario: Reject invalid patch bodies
- **WHEN** клиент передаёт пустой объект или поля вне `LessonPatch`, в том числе `group_id` или `status`
- **THEN** ответ имеет статус `422 VALIDATION_ERROR`; `details.fields` содержит `body` для пустого объекта или имена лишних полей
- **AND** невалидный JSON или неверный JSON-тип дают `400 BAD_REQUEST`

#### Scenario: Check existence and status before business rules
- **WHEN** тело соответствует контракту, но объединённое состояние нарушило бы BR-01 или BR-02, а занятие имеет статус, отличный от `PLANNED`
- **THEN** возвращается `409 LESSON_NOT_EDITABLE` с `details.current_status`, без предметных проверок и вызовов people-stub
- **AND** PATCH отсутствующего занятия с корректным телом возвращает `404 NOT_FOUND`

### Requirement: Revalidate the merged lesson before writing
Система SHALL применять общую проверку BR-01…BR-07 к объединённым полям с исходным ID в `exclude_lesson_id`. BR-05 и BR-06 SHALL исключать исходную запись. Предупреждения SHALL возвращаться в успешном ответе, а отказы проверки и people-stub SHALL сохранять исходную запись целиком.

#### Scenario: Count the candidate once
- **WHEN** изменяемое занятие сохраняет пересекающийся с исходной записью интервал и преподавателя, а его длительность равна доступному остатку дневной нормы
- **THEN** исходная запись не создаёт конфликт и не приводит к предупреждению о нагрузке

#### Scenario: Return warnings or reject a real conflict
- **WHEN** новое состояние проходит hard-правила, но превышает дневную норму и выходит за окна доступности
- **THEN** ответ `200` содержит `WORKLOAD_SOFT_LIMIT` и `INSTRUCTOR_UNAVAILABLE`
- **AND** при пересечении с другим активным занятием возвращается `409 SCHEDULE_CONFLICT` с деталями пересечения

#### Scenario: Preserve the original on a failure
- **WHEN** общая проверка отклоняет новое состояние или people-stub недоступен либо отвечает с превышением таймаута
- **THEN** ответ соответствует коду отказа по контракту, включая `502 UPSTREAM_UNAVAILABLE` и `504 UPSTREAM_TIMEOUT`
- **AND** все поля исходной записи, включая `updated_at`, сохраняются

### Requirement: Serialize edits and creation on shared resources
Система SHALL выполнять чтение актуальной версии, проверку, обновление и фиксацию PATCH в одной транзакции. PATCH одного занятия SHALL сериализоваться на его строке. POST и PATCH SHALL сериализовать проверку и запись по общим ресурсам; при PATCH протокол SHALL охватывать и прежние, и новые ресурсы.

#### Scenario: Recheck the destination after a competing write
- **WHEN** POST и PATCH одновременно претендуют на свободный интервал по общему ресурсу
- **THEN** первый успешный запрос занимает интервал, а ожидающий после commit возвращает `409 SCHEDULE_CONFLICT`
- **AND** это выполняется при обоих порядках записи

#### Scenario: Recheck the old resource after an edit ends
- **WHEN** POST ждёт завершения PATCH, освобождающего общий ресурс
- **THEN** после commit PATCH создание может занять освободившийся интервал
- **AND** после rollback PATCH исходная запись продолжает занимать интервал

#### Scenario: Merge two edits of the same lesson
- **WHEN** два PATCH одного занятия меняют разные поля и оба проходят проверки
- **THEN** итоговая запись содержит обе правки
- **AND** для одинакового поля сохраняется значение последнего успешно зафиксированного PATCH

#### Scenario: Serialize resource changes of different lessons
- **WHEN** PATCH разных занятий одновременно меняют ресурсы и используют общие ключи прежних или новых ресурсов
- **THEN** оба запроса завершаются с результатом по правилам расписания, без взаимной блокировки
