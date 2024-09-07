from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )
    telegram_token: str
    database_url: str
    database_key: str
    timeout: int = 20000
    summary_queue_url: str
    ya_api: str
    model: str = "gpt-4o-mini"
    model_summarizer: str = "gpt-4o-mini"
    x_telegram_bot_header: str
    openai_api_key: str
    context_size: int = 4096
    env: str = "dev"
