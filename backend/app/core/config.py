
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"

    ALPACA_API_KEY: str
    ALPACA_SECRET_KEY: str
    ALPACA_DATA_URL: str = "https://data.alpaca.markets"
    ALPACA_FEED: str = "iex"

    FMP_API_KEY: str | None = None

    DATABASE_URL: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
