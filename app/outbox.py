import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import OutboxEvent

logger = logging.getLogger(__name__)


async def add_outbox_event(
    session: AsyncSession, event_type: str, payload: dict
) -> None:
    """Кладёт событие в outbox в рамках той же транзакции, что и бизнес-данные."""
    session.add(OutboxEvent(event_type=event_type, payload=payload))


async def _publish_pending(publish_fn) -> None:
    async with AsyncSessionLocal() as session:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.published.is_(False))
            .order_by(OutboxEvent.created_at)
            .limit(settings.outbox_batch_size)
            .with_for_update(skip_locked=True)
        )
        events = (await session.execute(stmt)).scalars().all()

        for event in events:
            try:
                await publish_fn(event.event_type, event.payload)
                event.published = True
                event.published_at = datetime.now(timezone.utc)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to publish outbox event %s", event.id)
        await session.commit()


async def outbox_publisher_loop(publish_fn) -> None:
    """Фоновый воркер: переодически публикует неотправленные события."""
    while True:
        try:
            await _publish_pending(publish_fn)
        except Exception:  # noqa: BLE001
            logger.exception("Outbox publisher iteration failed")
        await asyncio.sleep(settings.outbox_poll_interval)