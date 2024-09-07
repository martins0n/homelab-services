from pydantic import BaseModel, Field


class TelegramUser(BaseModel):
    id: int
    is_bot: bool
    first_name: str | None
    username: str | None
    language_code: str
    is_premium: bool


class TelegramChat(BaseModel):
    id: int
    first_name: str
    username: str
    type: str


class TelegramMessage(BaseModel):
    message_id: int
    from_: TelegramUser = Field(..., alias="from")
    chat: TelegramChat
    date: int
    text: str


class TelegramRequest(BaseModel):
    update_id: int
    message: TelegramMessage
