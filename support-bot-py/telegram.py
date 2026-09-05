import os

from httpx import AsyncClient
from loguru import logger

# In --local mode the self-hosted Bot API server downloads the whole file from
# Telegram's DC *before* it answers getFile, so the response can take minutes on
# a large video. httpx's 5 s default read timeout turned that into a ReadTimeout
# (and orphaned the finished download in the shared volume). Cloud API answers
# getFile immediately, so it keeps a short-ish timeout.
GET_FILE_TIMEOUT_LOCAL = 900.0
GET_FILE_TIMEOUT_CLOUD = 60.0

# Telegram rejects a sendMessage over 4096 characters with
# 400 "message is too long", and the limit counts UTF-16 code units, not
# code points. Leave headroom for the entity offsets Telegram adds.
TELEGRAM_MESSAGE_LIMIT = 4000


def _tg_len(text: str) -> int:
    """Length as Telegram counts it: UTF-16 code units (astral chars cost 2)."""
    return len(text.encode("utf-16-le")) // 2


def _cut_at(text: str, limit: int) -> int:
    """Largest cut index whose prefix fits `limit`, never inside an HTML tag."""
    i = min(limit, len(text))
    while i > 1 and _tg_len(text[:i]) > limit:
        i -= 1
    opened = text.rfind("<", 0, i)
    if opened > 0 and text.find(">", opened, i) == -1:
        i = opened
    return max(i, 1)


def _split_line(line: str, limit: int) -> list[str]:
    """Break one over-long line on spaces, hard-cutting a word that still won't fit."""
    if _tg_len(line) <= limit:
        return [line]
    parts: list[str] = []
    cur = ""
    for word in line.split(" "):
        candidate = word if not cur else f"{cur} {word}"
        if _tg_len(candidate) <= limit:
            cur = candidate
            continue
        if cur:
            parts.append(cur)
            cur = ""
        while _tg_len(word) > limit:
            cut = _cut_at(word, limit)
            parts.append(word[:cut])
            word = word[cut:]
        cur = word
    if cur:
        parts.append(cur)
    return parts


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split `text` into chunks Telegram will accept, preferring line boundaries.

    Splitting on whole lines keeps parse_mode="HTML" valid: every tag this bot
    emits (<b>Speaker N:</b>, the source <a href>) lives within a single line, so
    no chunk can end mid-element. _cut_at guards the hard-split fallback.
    """
    if _tg_len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        for piece in _split_line(line, limit):
            candidate = piece if not cur else f"{cur}\n{piece}"
            if _tg_len(candidate) <= limit:
                cur = candidate
            else:
                if cur:
                    chunks.append(cur)
                cur = piece
    if cur:
        chunks.append(cur)
    return chunks


class TelegramBot:
    def __init__(self, token: str, local_api_url: str | None = None):
        self.token = token
        self.local_mode = bool(local_api_url)
        self.api_base_url = (local_api_url or "https://api.telegram.org").rstrip("/")

    def _bot_base(self) -> str:
        return f"{self.api_base_url}/bot{self.token}"

    async def send_message(self, chat_id: int, text: str, parse_mode: str = None):
        """Send `text`, split across several messages when it exceeds Telegram's
        4096-character limit (a long translation used to be lost to a 400)."""
        parts = split_message(text)
        async with AsyncClient(base_url=self._bot_base()) as client:
            for i, part in enumerate(parts, 1):
                payload = {
                    "chat_id": chat_id,
                    "text": part
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode

                result = await client.post(
                    "/sendMessage",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                suffix = f" (part {i}/{len(parts)})" if len(parts) > 1 else ""
                logger.info(
                    f"Sent message to chat {chat_id}{suffix} with status code {result.status_code}"
                )

                if result.status_code != 200:
                    logger.error(f"Telegram API error: {result.text}")
                    return

    async def get_file(self, file_id: str) -> dict:
        timeout = GET_FILE_TIMEOUT_LOCAL if self.local_mode else GET_FILE_TIMEOUT_CLOUD
        async with AsyncClient(base_url=self._bot_base()) as client:
            result = await client.post(
                "/getFile", json={"file_id": file_id}, timeout=timeout
            )
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
