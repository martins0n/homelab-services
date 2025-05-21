import pytest
import typing
from fastapi.testclient import TestClient
from support_bot_py.app.app import app
from support_bot_py.schemas import TelegramRequest, TelegramMessage, Chat, User
from respx import Router
from support_bot_py.settings import Settings
from pathlib import Path
from dotenv import load_dotenv

@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Loads test environment variables and returns Settings."""
    load_dotenv(Path(__file__).parent / ".env.test")
    return Settings()

@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    """Returns a TestClient for the FastAPI application."""
    return TestClient(app)

@pytest.fixture
def respx_router() -> typing.Generator[Router, None, None]:
    """Initializes and yields a respx.Router."""
    router = Router(assert_all_called=False)
    with router:
        yield router

def send_telegram_message(
    client: TestClient,
    message_text: str,
    chat_id: int = 123,
    user_id: int = 456,
) -> typing.Any:
    """
    Constructs and sends a Telegram message to the /webhook endpoint.
    """
    request_payload = TelegramRequest(
        update_id=1,
        message=TelegramMessage(
            message_id=100,
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Test"),
            text=message_text,
            date=1678886400,  # Example timestamp
        ),
    )
    response = client.post("/webhook", json=request_payload.model_dump(mode="json"))
    return response
