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
    news_job_enabled: bool = True
    news_job_hour: int = 15  # Hour of day to send news (24h format)
    news_default_days: int = 1  # Default days to look back for news
    news_channel_id: str | None = None  # Telegram channel ID to send newsletter to
    gmail_token_base64: str | None = None  # Base64 encoded token.pickle file
