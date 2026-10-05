from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_api_key: str = "super-secret-key"

    database_url: str = (
        "postgresql+asyncpg://payments:payments@localhost:5432/payments"
    )
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    outbox_poll_interval: float = 1.0
    outbox_batch_size: int = 50

    payments_queue: str = "payments.new"
    payments_dlx: str = "payments.dlx"
    payments_dlq: str = "payments.new.dlq"
    payments_exchange: str = "payments"
    payments_dlx_exchange: str = "payments.dlx.exchange"

    webhook_timeout: float = 5.0
    webhook_max_retries: int = 3


settings = Settings()