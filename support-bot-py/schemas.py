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


class TelegramMessageEntity(BaseModel):
    type: str
    offset: int
    length: int
    url: str | None = None


class TelegramQuote(BaseModel):
    text: str
    entities: list[TelegramMessageEntity] | None = None


class TelegramExternalReply(BaseModel):
    origin: dict | None = None
    chat: TelegramChat | None = None


class TelegramMessage(BaseModel):
    message_id: int
    from_: TelegramUser = Field(..., alias="from")
    chat: TelegramChat
    date: int
    text: str | None = None
    caption: str | None = None
    entities: list[TelegramMessageEntity] | None = None
    caption_entities: list[TelegramMessageEntity] | None = None
    quote: TelegramQuote | None = None
    external_reply: TelegramExternalReply | None = None


class TelegramRequest(BaseModel):
    update_id: int
    message: TelegramMessage
