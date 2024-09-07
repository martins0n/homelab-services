from typing import TypedDict

import tiktoken
from loguru import logger


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
