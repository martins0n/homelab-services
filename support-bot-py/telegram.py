from httpx import AsyncClient
from loguru import logger


class TelegramBot:
    def __init__(self, token: str):
        self.token = token

    async def send_message(self, chat_id: int, text: str, parse_mode: str = None):
        async with AsyncClient(
            base_url=f"https://api.telegram.org/bot{self.token}"
        ) as client:
            payload = {
                "chat_id": chat_id,
                "text": text
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

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

    async def get_file(self, file_id: str) -> dict:
        async with AsyncClient(
            base_url=f"https://api.telegram.org/bot{self.token}"
        ) as client:
            result = await client.post("/getFile", json={"file_id": file_id})
            if result.status_code != 200:
                logger.error(f"Telegram getFile error: {result.text}")
                result.raise_for_status()
            return result.json()["result"]

    async def download_file(self, file_path: str) -> bytes:
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        async with AsyncClient() as client:
            result = await client.get(url, timeout=60.0)
            if result.status_code != 200:
                logger.error(f"Telegram file download error: {result.status_code} {result.text[:200]}")
                result.raise_for_status()
            return result.content

    async def close(self):
        await self.client.aclose()
