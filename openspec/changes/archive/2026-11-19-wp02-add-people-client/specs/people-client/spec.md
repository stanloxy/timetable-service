## ADDED Requirements

### Requirement: Typed people-stub responses
Клиент SHALL асинхронно получать профиль преподавателя, недельную доступность преподавателя и данные аудитории по контракту `stubs/people-stub/stub-openapi.yaml`. Для каждого запроса клиент SHALL использовать `STUB_BASE_URL` и ограничивать длительность вызова значением `STUB_TIMEOUT_MS` (FR-12).

#### Scenario: Read a successful response from each endpoint
- **WHEN** клиент вызывает каждый из трёх методов, а настроенный `STUB_BASE_URL` возвращает соответствующий ответ `200`
- **THEN** каждый запрос отправляется по пути из контракта заглушки
- **AND** каждый метод возвращает типизированные данные своего эндпоинта

### Requirement: Concurrent collection of lesson reference data
Сервис SHALL одновременно запрашивать профиль и доступность преподавателя. Аудиторию SHALL запрашивать одновременно с ними только для формата `IN_PERSON` (FR-12).

#### Scenario: Collect data for an in-person lesson
- **WHEN** запрашиваются данные для очного занятия и все вызовы успешны
- **THEN** три вызова перекрываются по времени
- **AND** результат содержит профиль преподавателя, недельную доступность и аудиторию

#### Scenario: Collect data for an online lesson
- **WHEN** запрашиваются данные для онлайн-занятия и оба вызова успешны
- **THEN** вызовы профиля и доступности перекрываются по времени
- **AND** результат содержит профиль и недельную доступность
- **AND** запрос аудитории не выполняется

### Requirement: Contract errors for people-stub failures
Сервис SHALL распознавать отсутствие нужной сущности, отказ заглушки и истечение таймаута. На HTTP-границе ошибки SHALL представляться в формате и с кодами из `openapi.yaml` (FR-12, BR-03).

#### Scenario: Instructor resource is missing
- **WHEN** запрос профиля или недельной доступности преподавателя получает `404` от people-stub, без других отказов
- **THEN** на HTTP-границе ошибка преобразуется в `422 INSTRUCTOR_NOT_FOUND`

#### Scenario: Classroom is missing
- **WHEN** запрос аудитории получает `404` от people-stub, без других отказов
- **THEN** на HTTP-границе ошибка преобразуется в `422 CLASSROOM_NOT_FOUND`

#### Scenario: People-stub returns a server error
- **WHEN** один из необходимых запросов получает `5xx` от people-stub, без других отказов
- **THEN** на HTTP-границе ошибка преобразуется в `502 UPSTREAM_UNAVAILABLE`

#### Scenario: A request exceeds its timeout
- **WHEN** один из необходимых запросов превышает собственный `STUB_TIMEOUT_MS`, без других отказов
- **THEN** на HTTP-границе ошибка преобразуется в `504 UPSTREAM_TIMEOUT`

### Requirement: HTTP client shutdown
Приложение SHALL закрывать HTTP-клиент people-stub при завершении жизненного цикла.

#### Scenario: Release HTTP resources on shutdown
- **WHEN** приложение завершает работу после успешного запуска
- **THEN** HTTP-клиент закрыт к моменту завершения жизненного цикла

### Requirement: Reproducible async case
Параллельную сборку данных для очного занятия SHALL подтверждать тест с фейковым клиентом и искусственными задержками без сети. README SHALL содержать команду воспроизведения и фактически полученные результаты (NFR-07).

#### Scenario: Compare concurrent and sequential calls
- **WHEN** одинаковые три вызова фейкового клиента с искусственными задержками выполняются последовательно и через сборку данных для очного занятия
- **THEN** при последовательном выполнении одновременно активен максимум один вызов
- **AND** при параллельной сборке одновременно активны три вызова
- **AND** параллельная сборка занимает меньше времени
