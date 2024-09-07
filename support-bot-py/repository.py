import asyncio
from typing import Literal

from pydantic import BaseModel

from storage import client


class Message(BaseModel):
    content: str
    user: Literal["user"] | Literal["assistant"]


class MessageRepository:
    def __init__(self) -> None:
        self.client = client

    async def get_messages(self, chat_id: int, limit: int = 100) -> list[Message]:
        query = (
            self.client.table("message")
            .select("content, user")
            .eq("chat_id", chat_id)
            .order("created_at", desc=True)
            .limit(limit)
        )

        data = await asyncio.to_thread(query.execute)
        data = data.data
        data = data[::-1]
        return [Message(**message) for message in data]

    async def add_messages(self, chat_id: int, messages: list[Message]) -> None:
        query = self.client.table("message").insert(
            [{**message, "chat_id": chat_id} for message in messages]
        )

        await asyncio.to_thread(query.execute)

    async def ping(self) -> bool:
        query = (
            self.client.table("message")
            .select("created_at")
            .order("created_at", desc=True)
            .limit(1)
        )

        data = await asyncio.to_thread(query.execute)
        return data.data
