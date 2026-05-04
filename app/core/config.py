from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nova:nova@localhost:5432/nova"
    environment: str = "development"
    log_level: str = "info"
    cognito_region: str = "us-east-1"
    cognito_buyer_pool_id: str = ""


settings = Settings()
