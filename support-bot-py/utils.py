from typing import Annotated, TypedDict

import tiktoken
from fastapi import Header, HTTPException
from loguru import logger


def create_verify_token_function(x_telegram_bot_header):
    async def verify_token(x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None):
        if x_telegram_bot_api_secret_token is None:
            raise HTTPException(status_code=200, detail="Unauthorized")
        if x_telegram_bot_api_secret_token != x_telegram_bot_header:
            raise HTTPException(status_code=200, detail="Invalid token")
    return verify_token


class Message(TypedDict):
    content: str
    role: str


def filter_context_size(
    messages: list[Message], context_size: int, model: str
) -> list[Message]:
    tokenizer = tiktoken.encoding_for_model(model)

    messages_length = [len(tokenizer.encode(m["content"])) for m in messages]

    total_length = 0
    for i, length in enumerate(messages_length[::-1]):
        total_length += length
        if total_length > context_size:
            break
    logger.info(f"Total length: {total_length}")

    if i == 0:
        return messages[-1:]
    return messages[-i:]
