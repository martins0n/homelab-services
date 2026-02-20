import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import ASGITransport, AsyncClient

# Minimal env so Settings() doesn't fail — must be set before app import
os.environ.setdefault("TELEGRAM_TOKEN", "testtoken")
# Supabase validates the key is a JWT — use a minimal valid JWT
os.environ.setdefault(
    "DATABASE_KEY",
    "eyJhbGciOiAiSFMyNTYiLCAidHlwIjogIkpXVCJ9"
    ".eyJyb2xlIjogImFub24iLCAiaXNzIjogInN1cGFiYXNlIn0"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
)
os.environ.setdefault("DATABASE_URL", "https://test.supabase.co")
os.environ.setdefault("X_TELEGRAM_BOT_HEADER", "test-header")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("ENV", "dev")  # disables webhook token check
os.environ.setdefault("NEWS_JOB_ENABLED", "false")  # don't start scheduler
os.environ.setdefault("SUMMARY_QUEUE_URL", "https://test-queue.example.com")
os.environ.setdefault("YA_API", "test-ya-api-key")

from app import app  # noqa: E402


def make_payload(text: str, chat_id: int = 100) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": 200, "is_bot": False, "username": "tester"},
            "chat": {"id": chat_id, "type": "private"},
            "date": 0,
            "text": text,
        },
    }


async def wait_for_background_tasks() -> None:
    """Gather all pending asyncio tasks (background handlers) before asserting."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def telegram_mock():
    """Intercept outbound calls to the Telegram Bot API via respx.

    TelegramBot.send_message creates a fresh httpx.AsyncClient on every call,
    so respx (which patches at the class level) catches it reliably.
    """
    with respx.mock(base_url="https://api.telegram.org", assert_all_called=False) as mock:
        mock.post("/bottesttoken/sendMessage").respond(
            200, json={"ok": True, "result": {"message_id": 42}}
        )
        yield mock


@pytest.fixture
def openai_mock():
    """Patch app.openai.chat.completions.create directly with AsyncMock.

    The OpenAI SDK creates its httpx.AsyncClient at module-import time with a
    custom transport, so respx cannot intercept it reliably at the HTTP layer.
    Direct patching is more robust.
    """
    mock_msg = MagicMock()
    mock_msg.content = "mocked response"
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]

    with patch("app.openai.chat.completions.create", new_callable=AsyncMock, return_value=mock_resp):
        yield mock_resp


@pytest.fixture
def supabase_mock():
    """Patch MessageRepository methods directly.

    Supabase's sync client runs in asyncio.to_thread which makes it awkward to
    intercept at the HTTP layer; patching the repository methods is simpler and
    avoids real network calls.
    """
    with patch("app.message_repository.get_messages", new_callable=AsyncMock, return_value=[]) as get_mock, \
         patch("app.message_repository.add_messages", new_callable=AsyncMock) as add_mock:
        yield {"get": get_mock, "add": add_mock}
