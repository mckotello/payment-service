import asyncio
import logging
import random
from datetime import datetime, timezone

import httpx
from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitMessage

from app.broker import (
    broker,
    payments_dlq_queue,
    payments_exchange,
    payments_new_queue,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Payment, PaymentStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastStream(broker)


async def _process_payment(payment_id: str) -> None:
    await asyncio.sleep(random.uniform(2, 5))
    async with AsyncSessionLocal() as session:
        payment = await session.get(Payment, __import__("uuid").UUID(payment_id))
        if payment is None:
            logger.warning("Payment %s not found", payment_id)
            return
        if payment.status != PaymentStatus.PENDING:
            logger.info("Payment %s already processed", payment_id)
            return
        success = random.random() < 0.9
        payment.status = PaymentStatus.SUCCEEDED if success else PaymentStatus.FAILED
        payment.processed_at = datetime.now(timezone.utc)
        await session.commit()


async def _send_webhook(payment_id: str, status: str) -> None:
    async with AsyncSessionLocal() as session:
        payment = await session.get(Payment, __import__("uuid").UUID(payment_id))
        if payment is None:
            return
        url = payment.webhook_url
        payload = {
            "payment_id": str(payment.id),
            "status": status,
            "processed_at": payment.processed_at.isoformat()
            if payment.processed_at
            else None,
        }

    last_exc: Exception | None = None
    for attempt in range(1, settings.webhook_max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.webhook_timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                logger.info("Webhook delivered for %s (attempt %s)", payment_id, attempt)
                return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            delay = 2 ** (attempt - 1)
            logger.warning(
                "Webhook attempt %s failed for %s: %s. Retry in %ss",
                attempt, payment_id, exc, delay,
            )
            await asyncio.sleep(delay)

    raise RuntimeError(f"Webhook failed after retries: {last_exc}")


@broker.subscriber(
    payments_new_queue,
    exchange=payments_exchange,
    retry=3,
)
async def handle_payment_new(body: dict, msg: RabbitMessage) -> None:
    payment_id = body.get("payment_id")
    if not payment_id:
        logger.error("No payment_id in message: %s", body)
        return

    logger.info("Processing payment %s", payment_id)
    await _process_payment(payment_id)
    await _send_webhook(payment_id, "processed")
    logger.info("Payment %s handled", payment_id)


@broker.subscriber(payments_dlq_queue)
async def handle_dlq(body: dict, msg: RabbitMessage) -> None:
    logger.error("DLQ received message: %s", body)


if __name__ == "__main__":
    app.run()