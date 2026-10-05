import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker import broker, publish_payment_new
from app.database import get_session
from app.models import Payment, PaymentStatus
from app.outbox import add_outbox_event, outbox_publisher_loop
from app.schemas import (
    PaymentCreate,
    PaymentCreatedResponse,
    PaymentResponse,
)
from app.security import verify_api_key

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broker.connect()
    publisher_task = asyncio.create_task(outbox_publisher_loop(publish_payment_new))
    try:
        yield
    finally:
        publisher_task.cancel()
        try:
            await publisher_task
        except asyncio.CancelledError:
            pass
        await broker.close()


app = FastAPI(title="Payment Service", lifespan=lifespan)


@app.post(
    "/api/v1/payments",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentCreatedResponse,
    dependencies=[Depends(verify_api_key)],
)
async def create_payment(
    payload: PaymentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
):
    # Идемпотентность: если платёж с таким ключом уже есть — вернуть его.
    existing = (
        await session.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing:
        return PaymentCreatedResponse(
            payment_id=existing.id,
            status=existing.status,
            created_at=existing.created_at,
        )

    payment = Payment(
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        meta=payload.metadata,
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
        webhook_url=str(payload.webhook_url),
    )
    session.add(payment)

    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = (
            await session.execute(
                select(Payment).where(Payment.idempotency_key == idempotency_key)
            )
        ).scalar_one()
        return PaymentCreatedResponse(
            payment_id=existing.id,
            status=existing.status,
            created_at=existing.created_at,
        )

    # Событие в outbox в той же транзакции.
    await add_outbox_event(
        session,
        event_type="payment.new",
        payload={"payment_id": str(payment.id)},
    )
    await session.commit()

    return PaymentCreatedResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@app.get(
    "/api/v1/payments/{payment_id}",
    response_model=PaymentResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_payment(
    payment_id: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        import uuid as _uuid

        pid = _uuid.UUID(payment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment_id")

    payment = await session.get(Payment, pid)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment