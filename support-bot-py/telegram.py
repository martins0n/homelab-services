from httpx import AsyncClient
from loguru import logger


class TelegramBot:
    def __init__(self, token: str):
        self.token = token

    async def send_message(self, chat_id: int, text: str):
        async with AsyncClient(
            base_url=f"https://api.telegram.org/bot{self.token}"
        ) as client:
            payload = {
                "chat_id": chat_id, 
                "text": text
            }
            
            result = await client.post(
                "/sendMessage",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            logger.info(
                f"Sent message to chat {chat_id} with status code {result.status_code}"
            )
            
            if result.status_code != 200:
                logger.error(f"Telegram API error: {result.text}")

    async def close(self):
        await self.client.aclose()
