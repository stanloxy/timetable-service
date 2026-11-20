# service-readiness Specification

## Purpose
Сообщать через HTTP о готовности сервиса работать с PostgreSQL и RabbitMQ и показывать результат проверки каждой зависимости (TASK.md, §3.6).

## Requirements

### Requirement: Report each dependency independently
`GET /health/ready` SHALL параллельно проверять PostgreSQL и доступность RabbitMQ по AMQP. Каждая проверка SHALL иметь лимит две секунды. Ответ SHALL соответствовать `openapi.yaml` и содержать `status`, `db` и `broker`. Проверки SHALL обходиться без публикации событий и вызовов people-stub.

#### Scenario: Both dependencies respond
- **WHEN** PostgreSQL и RabbitMQ отвечают в пределах лимита
- **THEN** ответ имеет статус `200` и тело `{"status":"ok","db":"ok","broker":"ok"}`

#### Scenario: Broker is unavailable
- **WHEN** PostgreSQL отвечает, а RabbitMQ недоступен или его проверка превышает лимит
- **THEN** ответ имеет статус `503` и тело `{"status":"degraded","db":"ok","broker":"fail"}`

#### Scenario: Database is unavailable
- **WHEN** PostgreSQL недоступен или его проверка превышает лимит
- **THEN** ответ имеет статус `503` с `status: degraded` и `db: fail`
- **AND** `broker` сообщает фактический результат проверки RabbitMQ

### Requirement: Recover broker readiness without restarting the application
При `BROKER=rabbitmq` приложение SHALL использовать `BROKER_URL` для подключения к RabbitMQ. Старт приложения SHALL обходиться без ожидания доступности брокера. Проверка или отправка SHALL иметь возможность повторно подключиться после отказа. Приложение SHALL освобождать AMQP-ресурсы при остановке. `GET /health/live` SHALL возвращать `200` независимо от доступности RabbitMQ, пока процесс отвечает.

#### Scenario: Start during a broker outage and recover
- **WHEN** приложение запускается при недоступном RabbitMQ и доступном PostgreSQL
- **THEN** `/health/live` возвращает `200`, а `/health/ready` возвращает `503` с `broker: fail`
- **AND** после восстановления RabbitMQ `/health/ready` возвращает `200` без перезапуска приложения
