import pytest_asyncio
import os
import asyncio
from supabase import create_client, Client
from dotenv import load_dotenv

# Assuming pytest is run from the root of the 'support-bot-py' project directory
from repository import MessageRepository, Message
from settings import Settings

# Load environment variables from .env file for local testing
# This allows developers to set TEST_DATABASE_URL and TEST_DATABASE_KEY locally
# without committing them.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

@pytest_asyncio.fixture(scope="session")
def test_settings() -> Settings:
    # These environment variables (TEST_DATABASE_URL, TEST_DATABASE_KEY)
    # must be set in the testing environment (e.g., .env file or CI secrets)
    # Default values are provided for local Supabase Docker instances if not set.
    return Settings(
        database_url=os.getenv("TEST_DATABASE_URL", "http://localhost:54321"),
        database_key=os.getenv("TEST_DATABASE_KEY", "your-anon-key"), # Replace with actual default anon key for Supabase local
        telegram_token="test_token_dummy",
        summary_queue_url="test_url_dummy",
        ya_api="test_api_dummy",
        spam_list="http://example.com/spam_list_dummy",
        openai_api_key="test_openai_key_dummy",
        x_telegram_bot_header="test_header_dummy",
        # Ensure all other required Settings fields have dummy values
        telegram_spam_bot_token="test_spam_token_dummy",
        x_telegram_spam_bot_header="test_spam_header_dummy",
        env="test"
    )

@pytest_asyncio.fixture(scope="session")
def supabase_client(test_settings: Settings) -> Client:
    # print(f"Creating Supabase client for URL: {test_settings.database_url}") # For debugging
    client = create_client(test_settings.database_url, test_settings.database_key)
    return client

@pytest_asyncio.fixture
async def message_repository(supabase_client: Client) -> MessageRepository:
    repo = MessageRepository()
    # Crucially, override the client instance in the repository
    repo.client = supabase_client

    # Optional: Clean up messages before each test run for this repository.
    # This is a basic cleanup and might need to be more robust depending on RLS
    # and test complexity. For now, tests will use unique chat_ids or manage their own state.
    # Example:
    # try:
    #     await asyncio.to_thread(
    #         supabase_client.table("message").delete().neq("content", "intentionally_persistent_marker").execute
    #     )
    # except Exception as e:
    #     print(f"Could not clean message table (may not exist yet or RLS): {e}")

    return repo

# Added content starts here
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Add new imports if necessary for ban_bot testing
# from ban_bot.gpt import Settings # gpt.py also has its own Settings import
# The line above is commented out as per the provided code block.
# The main Settings from the root 'settings.py' should be sufficient if ban_bot.gpt uses it consistently
# or relies on environment variables that test_settings helps define.

# Fixture to load mock spam examples
@pytest_asyncio.fixture
def mock_spam_examples_content() -> str:
    # Path is relative to the root of the project (support-bot-py)
    # if pytest is run from there.
    path = os.path.join(os.path.dirname(__file__), "data", "mock_spam_examples.json")
    with open(path, 'r') as f:
        return f.read()

# Fixture to mock httpx.AsyncClient.get for spam examples
@pytest_asyncio.fixture
def mock_httpx_get_spam_examples(mock_spam_examples_content: str):
    mock_response = MagicMock()
    mock_response.json = MagicMock(return_value=json.loads(mock_spam_examples_content))

    # The target for patch should be where the object is *used*.
    # In ban_bot/gpt.py, it's `import httpx`, then `httpx.AsyncClient`.
    # So we patch 'ban_bot.gpt.httpx.AsyncClient'.
    with patch('ban_bot.gpt.httpx.AsyncClient') as mock_async_client_constructor:
        mock_instance = AsyncMock() # The instance of AsyncClient
        mock_instance.get = AsyncMock(return_value=mock_response) # Mock its get method

        mock_instance.__aenter__.return_value = mock_instance # Return self for context manager
        mock_instance.__aexit__.return_value = None

        mock_async_client_constructor.return_value = mock_instance
        yield mock_async_client_constructor


# Fixture to mock ChatOpenAI and LLMChain
@pytest_asyncio.fixture
def mock_llm_stuff():
    # Mock for ChatOpenAI instance
    mock_chat_openai_instance = AsyncMock()

    # Mock for LLMChain instance
    mock_llm_chain_instance = AsyncMock()

    # Patch where ChatOpenAI and LLMChain are imported/used in ban_bot.gpt
    # In ban_bot/gpt.py:
    # from langchain.chat_models import ChatOpenAI
    # from langchain.chains.llm import LLMChain
    # So we patch 'ban_bot.gpt.ChatOpenAI' and 'ban_bot.gpt.LLMChain'
    with patch('ban_bot.gpt.ChatOpenAI', return_value=mock_chat_openai_instance) as mock_chat_openai, \
         patch('ban_bot.gpt.LLMChain', return_value=mock_llm_chain_instance) as mock_llm_chain:
        yield {
            "chat_openai": mock_chat_openai,
            "llm_chain": mock_llm_chain,
            "llm_chain_instance": mock_llm_chain_instance
        }

# Fixture to reset spam_examples cache in ban_bot.gpt
# This is important because spam_examples is a global variable in gpt.py
@pytest_asyncio.fixture(autouse=True)
def reset_spam_examples_cache():
    from ban_bot import gpt as ban_bot_gpt_module
    # It's possible ban_bot_gpt_module might not be found if ban_bot is not installed/discoverable
    # during conftest collection in some environments.
    # A try-except ModuleNotFoundError might be needed if issues arise.
    try:
        from ban_bot import gpt as ban_bot_gpt_module
        original_spam_examples = ban_bot_gpt_module.spam_examples
        ban_bot_gpt_module.spam_examples = None
        yield
        ban_bot_gpt_module.spam_examples = original_spam_examples
    except ImportError:
        # If ban_bot module is not found, this fixture does nothing.
        # This might happen if tests are run in an environment where ban_bot isn't directly on pythonpath
        # though for this project structure it should be.
        yield


# New fixtures for ban_bot_router testing
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient # Renamed to avoid clash
from ban_bot.ban_bot import router as ban_bot_router
# Assuming TelegramBot is imported in ban_bot.ban_bot or accessible for patching

# Fixture for a TestClient specifically for the ban_bot router
@pytest_asyncio.fixture
def ban_bot_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ban_bot_router)
    return app

@pytest_asyncio.fixture
def ban_bot_client(ban_bot_test_app: FastAPI) -> FastAPITestClient:
    return FastAPITestClient(ban_bot_test_app)

# Fixture to mock TelegramBot used by the ban_bot router
@pytest_asyncio.fixture
def mock_telegram_bot_in_ban_bot():
    # ban_bot.ban_bot.py uses:
    # from telegram import TelegramBot
    # settings = Settings()
    # bot = TelegramBot(token=settings.telegram_spam_bot_token)
    # So, we need to patch 'ban_bot.ban_bot.TelegramBot'
    try:
        with patch('ban_bot.ban_bot.TelegramBot', autospec=True) as mock_class:
            mock_instance = mock_class.return_value # This is the instance that would be `bot`
            mock_instance.send_message = AsyncMock()
            mock_instance.ban_chat_member = AsyncMock()
            mock_instance.delete_message = AsyncMock()
            yield mock_instance
    except ImportError:
        # Handle cases where ban_bot.ban_bot might not be importable during test collection
        # (e.g. if tests are collected from a different CWD or structure)
        # For this project, it should be fine.
        yield AsyncMock() # yield a dummy mock to satisfy fixture dependencies

# Fixtures for main app testing (app.py)
# We need to import app AFTER settings might be patched or env vars set.
# Pytest typically handles fixture setup before test collection/imports in test files.
# However, app.py has module-level initializations.
# The `main_app_client` fixture will manage patching for its scope.

from app import app as main_fastapi_app # The FastAPI app from app.py

# Fixture for the main FastAPI app's TestClient
@pytest_asyncio.fixture(scope="session")
def main_app_client(test_settings: Settings, supabase_client: Client) -> FastAPITestClient:
    # Patch app.settings and storage.client for the entire session
    # so that when app.py is imported (either here or by test files),
    # its global variables use these test configurations.
    with patch('app.settings', new=test_settings), \
         patch('storage.client', new=supabase_client):
        client = FastAPITestClient(main_fastapi_app)
        yield client

# Mock for app.telegram_bot
@pytest_asyncio.fixture
def mock_main_telegram_bot():
    # Patches app.telegram_bot which is an instance of TelegramBot in app.py
    with patch('app.telegram_bot', new_callable=AsyncMock) as mock_bot_instance:
        # Ensure methods called by app.py handlers are present on the mock
        mock_bot_instance.send_message = AsyncMock()
        # Add other methods like delete_message, ban_chat_member if used by main app handlers
        yield mock_bot_instance

# Mock for app.openai.chat.completions.create
@pytest_asyncio.fixture
def mock_main_openai_completions_create():
    # app.py uses: response = await openai.chat.completions.create(...)
    # So we need to mock this specific method call on the app.openai instance.
    with patch('app.openai.chat.completions.create', new_callable=AsyncMock) as mock_create:
        yield mock_create

# Fixture for app.message_repository (the actual instance from app.py, but ensured to use test DB)
@pytest_asyncio.fixture
def app_message_repo(main_app_client): # Depends on main_app_client to ensure patches are active
    # The main_app_client fixture ensures that storage.client (used by MessageRepository in app.py)
    # is patched to use the test Supabase client.
    from app import message_repository
    return message_repository
