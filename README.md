# Payment Processing Service

Асинхронный микросервис процессинга платежей: FastAPI + SQLAlchemy 2.0 (async) +
PostgreSQL + RabbitMQ (FastStream) + Outbox pattern + DLQ.

## Запуск

```bash
cp .env.example .env
docker-compose up --build
```

- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- RabbitMQ UI: http://localhost:15672 (guest/guest)

## API

Все эндпоинты требуют заголовок `X-API-Key: super-secret-key`.

### Создание платежа

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H "X-API-Key: super-secret-key" \
  -H "Idempotency-Key: order-42" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "100.50",
    "currency": "USD",
    "description": "Order #42",
    "metadata": {"user_id": 7},
    "webhook_url": "https://webhook.site/your-uuid"
  }'
```

Ответ `202 Accepted`:

```json
{
  "payment_id": "0b1f...",
  "status": "pending",
  "created_at": "2024-01-01T12:00:00+00:00"
}
```

Повторный запрос с тем же `Idempotency-Key` вернёт тот же `payment_id` без создания дубля.

### Получение платежа

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: super-secret-key"
```

## Архитектура

1. `POST /api/v1/payments` в одной транзакции пишет `payments` и `outbox`.
2. Фоновый outbox-publisher читает `outbox` и публикует в exchange `payments`
   → очередь `payments.new`.
3. Consumer (`payments.new`):
   - эмулирует обработку 2–5 сек, 90% успех / 10% ошибка;
   - обновляет `status`/`processed_at`;
   - шлёт webhook (3 попытки, экспоненциальная задержка).
4. Если webhook окончательно упал — сообщение уходит в DLQ `payments.new.dlq`
   через `x-dead-letter-exchange` (retry=3 в FastStream).

## Переменные окружения

| Имя | Описание |
|-----|----------|
| `APP_API_KEY` | Статический API ключ |
| `DATABASE_URL` | DSN PostgreSQL (asyncpg) |
| `RABBITMQ_URL` | DSN RabbitMQ |