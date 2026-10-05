from faststream.rabbit import (
    ExchangeType,
    RabbitBroker,
    RabbitExchange,
    RabbitQueue,
)
from faststream.rabbit.schemas import QueueType

from app.config import settings

broker = RabbitBroker(settings.rabbitmq_url)

payments_exchange = RabbitExchange(
    settings.payments_exchange,
    type=ExchangeType.DIRECT,
    durable=True,
)

payments_dlx_exchange = RabbitExchange(
    settings.payments_dlx_exchange,
    type=ExchangeType.DIRECT,
    durable=True,
)

payments_new_queue = RabbitQueue(
    settings.payments_queue,
    durable=True,
    routing_key=settings.payments_queue,
    queue_type=QueueType.QUORUM,
    arguments={
        "x-dead-letter-exchange": settings.payments_dlx_exchange,
        "x-dead-letter-routing-key": settings.payments_dlq,
    },
)

payments_dlq_queue = RabbitQueue(
    settings.payments_dlq,
    durable=True,
    routing_key=settings.payments_dlq,
    queue_type=QueueType.QUORUM,
)


async def publish_payment_new(event_type: str, payload: dict) -> None:
    """publish_fn для outbox. Публикует событие в payments.new."""
    await broker.publish(
        payload,
        exchange=payments_exchange,
        routing_key=settings.payments_queue,
        persist=True,
    )