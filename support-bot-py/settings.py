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
    spam_list: str | None = None
    telegram_spam_bot_token: str | None = None
    x_telegram_spam_bot_header: str | None = None
    model: str = "gpt-4o-mini"
    model_summarizer: str = "gpt-4o-mini"
    model_spam: str = "gpt-4o-mini"
    x_telegram_bot_header: str
    openai_api_key: str
    context_size: int = 4096
    env: str = "dev"
    youtube_proxy_url: str | None = None
