import os

from httpx import AsyncClient
from loguru import logger


class TelegramBot:
    def __init__(self, token: str, local_api_url: str | None = None):
        self.token = token
        self.local_mode = bool(local_api_url)
        self.api_base_url = (local_api_url or "https://api.telegram.org").rstrip("/")

    def _bot_base(self) -> str:
        return f"{self.api_base_url}/bot{self.token}"

    async def send_message(self, chat_id: int, text: str, parse_mode: str = None):
        async with AsyncClient(base_url=self._bot_base()) as client:
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
        async with AsyncClient(base_url=self._bot_base()) as client:
            result = await client.post("/getFile", json={"file_id": file_id})
            if result.status_code != 200:
                logger.error(f"Telegram getFile error: {result.text}")
                result.raise_for_status()
            return result.json()["result"]

    async def download_file(self, file_path: str) -> bytes:
        if self.local_mode:
            # In local mode, getFile already returned an absolute filesystem path.
            # Read and then unlink so the shared volume doesn't accumulate files.
            try:
                with open(file_path, "rb") as f:
                    return f.read()
            finally:
                try:
                    os.unlink(file_path)
                except OSError as e:
                    logger.warning(f"failed to unlink {file_path}: {e}")

        url = f"{self.api_base_url}/file/bot{self.token}/{file_path}"
        async with AsyncClient() as client:
            result = await client.get(url, timeout=60.0)
            if result.status_code != 200:
                logger.error(f"Telegram file download error: {result.status_code} {result.text[:200]}")
                result.raise_for_status()
            return result.content

    async def send_audio(
        self,
        chat_id: int,
        audio_bytes: bytes,
        filename: str = "audio.mp3",
        caption: str | None = None,
        title: str | None = None,
    ):
        """Send an audio file as a multipart upload. Telegram shows an inline audio
        player (works on Android, unlike Telegraph Read Aloud). Used to read
        translated transcripts aloud."""
        async with AsyncClient(base_url=self._bot_base()) as client:
            data = {"chat_id": str(chat_id)}
            if caption:
                data["caption"] = caption
            if title:
                data["title"] = title
            files = {"audio": (filename, audio_bytes, "audio/mpeg")}
            result = await client.post("/sendAudio", data=data, files=files, timeout=120.0)
            logger.info(
                f"Sent audio to chat {chat_id} with status code {result.status_code}"
            )
            if result.status_code != 200:
                logger.error(f"Telegram sendAudio error: {result.text}")

    async def close(self):
        await self.client.aclose()
