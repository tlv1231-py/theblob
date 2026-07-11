from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = Field(..., description="PostgreSQL connection string")

    # Market Data
    yfinance_enabled: bool = True
    finnhub_api_key: str = ""
    alpha_vantage_api_key: str = ""

    # Execution
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    # Alerts
    discord_webhook_url: str = ""

    # Runtime
    env: str = "development"
    log_level: str = "INFO"


settings = Settings()
