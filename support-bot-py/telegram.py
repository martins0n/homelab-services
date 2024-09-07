from httpx import AsyncClient
from loguru import logger


class TelegramBot:
    def __init__(self, token: str):
        self.token = token

    async def send_message(self, chat_id: int, text: str):
        async with AsyncClient(
            base_url=f"https://api.telegram.org/bot{self.token}"
        ) as client:
            result = await client.post(
                "/sendMessage",
                json={"chat_id": chat_id, "text": text},
                headers={"Content-Type": "application/json"},
            )
            logger.info(
                f"Sent message to chat {chat_id} with status code {result.status_code}"
            )

    async def close(self):
        await self.client.aclose()
