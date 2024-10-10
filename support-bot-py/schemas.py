from pydantic import BaseModel, Field


class TelegramUser(BaseModel):
    id: int
    is_bot: bool
    username: str | None = None
    is_premium: bool | None = None
    language_code: str | None = None
    first_name: str | None = None

class TelegramChat(BaseModel):
    id: int
    type: str
    first_name: str | None = None
    username: str | None = None


class TelegramMessage(BaseModel):
    message_id: int
    from_: TelegramUser = Field(..., alias="from")
    chat: TelegramChat
    date: int
    text: str | None = None


class TelegramRequest(BaseModel):
    update_id: int
    message: TelegramMessage
