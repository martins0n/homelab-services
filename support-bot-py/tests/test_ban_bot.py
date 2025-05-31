import pytest
import asyncio
from unittest.mock import AsyncMock

# Assuming pytest is run from the root of the 'support-bot-py' project directory
from ban_bot.gpt import check_spam, Settings as BanBotSettings # ban_bot.gpt might use its own Settings import

# Use the existing test_settings fixture for overall settings if needed,
# but check_spam primarily relies on mocks for external services.

@pytest.mark.asyncio
async def test_check_spam_not_spam(mock_httpx_get_spam_examples, mock_llm_stuff):
    # Configure the mock LLMChain to return a "not spam" verdict
    mock_llm_stuff["llm_chain_instance"].arun = AsyncMock(
        return_value="Reason: It's a friendly message.\nVerdict: No"
    )

    is_spam, reason = await check_spam("Hello, how are you?")

    assert is_spam is False
    assert "Verdict: No" in reason
    # Check that httpx.AsyncClient was called (implicitly by mock_httpx_get_spam_examples setup)
    mock_httpx_get_spam_examples.assert_called()
    # Check that ChatOpenAI and LLMChain were instantiated
    mock_llm_stuff["chat_openai"].assert_called()
    mock_llm_stuff["llm_chain"].assert_called()
    # Check that arun was called on the LLMChain instance
    mock_llm_stuff["llm_chain_instance"].arun.assert_called_with(["Hello, how are you?"])


@pytest.mark.asyncio
async def test_check_spam_is_spam(mock_httpx_get_spam_examples, mock_llm_stuff):
    # Configure the mock LLMChain to return a "spam" verdict
    mock_llm_stuff["llm_chain_instance"].arun = AsyncMock(
        return_value="Reason: Contains suspicious links and offers.\nVerdict: Yes"
    )

    is_spam, reason = await check_spam("Buy cheap watches now! example.com/cheap-watches")

    assert is_spam is True
    assert "Verdict: Yes" in reason
    mock_llm_stuff["llm_chain_instance"].arun.assert_called_with(["Buy cheap watches now! example.com/cheap-watches"])

@pytest.mark.asyncio
async def test_check_spam_uses_cached_examples(mock_httpx_get_spam_examples, mock_llm_stuff):
    # First call, httpx should be used
    mock_llm_stuff["llm_chain_instance"].arun = AsyncMock(return_value="Verdict: No")
    await check_spam("First message")

    # Assert that the constructor of httpx.AsyncClient (which mock_httpx_get_spam_examples patches) was called
    assert mock_httpx_get_spam_examples.call_count == 1
    # Get the actual httpx.AsyncClient *instance*'s mock (the result of the constructor call)
    mock_async_client_instance = mock_httpx_get_spam_examples.return_value
    # Assert that its 'get' method was called
    mock_async_client_instance.get.assert_called_once()

    # Second call, httpx.AsyncClient's get should not be called again due to caching
    await check_spam("Second message")
    # The constructor might be called again if the client is created per call, but get should not.
    # Let's re-check check_spam: `async with httpx.AsyncClient(...)`. Yes, it's created per call if spam_examples is None.
    # The cache we are testing is `global spam_examples`.
    # So, the constructor `mock_httpx_get_spam_examples` will be called once.
    # The `get` method on its *instance* will be called once.

    # mock_httpx_get_spam_examples is the mock for the *constructor* `httpx.AsyncClient`
    # Its `return_value` is the mock for the *instance* of `AsyncClient`.
    # `get` is a method of the instance.

    # After the first call, `spam_examples` in gpt.py is populated.
    # The `reset_spam_examples_cache` fixture ensures it's None before this test.

    # So, for the second call to check_spam:
    # 1. `ban_bot_gpt_module.spam_examples` is NOT None.
    # 2. The `if spam_examples is None:` block in `check_spam` is skipped.
    # 3. `httpx.AsyncClient(...).get(...)` is NOT called.

    # Therefore, the call count for `mock_async_client_instance.get` should remain 1.
    mock_async_client_instance.get.assert_called_once()

    # The LLM chain's arun method should be called for each check_spam call
    assert mock_llm_stuff["llm_chain_instance"].arun.call_count == 2

# New tests for ban_bot_router
from fastapi.testclient import TestClient as FastAPITestClient # Ensure TestClient is imported
from unittest.mock import patch as unittest_patch # Alias to avoid confusion with pytest's patch

# Test for the /spam endpoint
BASE_SPAM_URL = "/spam" # Assuming the router is mounted at root for the test client

@pytest.mark.asyncio
async def test_ban_bot_router_spam_detected_and_banned(
    ban_bot_client: FastAPITestClient,
    mock_telegram_bot_in_ban_bot: AsyncMock # This is the mocked TelegramBot instance
):
    # Mock ban_bot.ban_bot.check_spam (which is imported from ban_bot.gpt)
    # The router itself calls check_spam.
    # In ban_bot.ban_bot.py: from .gpt import check_spam
    with unittest_patch('ban_bot.ban_bot.check_spam', new_callable=AsyncMock) as mock_check_spam:
        mock_check_spam.return_value = (True, "Reason: It's clearly spam!\nVerdict: Yes") # (is_spam, reason)

        webhook_payload = {
            "update_id": 10000,
            "message": {
                "message_id": 101,
                "chat": {"id": 12345, "type": "group", "title": "Test Group"},
                "from": {"id": 67890, "is_bot": False, "first_name": "spammer", "username": "spammer"},
                "date": 1678886400, # Some timestamp
                "text": "Buy my course!"
            }
        }

        response = ban_bot_client.post(BASE_SPAM_URL, json=webhook_payload)

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "is_spam": True}

        mock_check_spam.assert_called_once_with("Buy my course!")

        mock_telegram_bot_in_ban_bot.ban_chat_member.assert_called_once_with(12345, 67890)

        expected_reason_text = "Reason: It's clearly spam!\nVerdict: Yes"
        mock_telegram_bot_in_ban_bot.send_message.assert_called_once_with(
            12345,
            f"User @spammer banned for spam.\nReason: {expected_reason_text}"
        )
        mock_telegram_bot_in_ban_bot.delete_message.assert_called_once_with(12345, 101)

@pytest.mark.asyncio
async def test_ban_bot_router_not_spam(
    ban_bot_client: FastAPITestClient,
    mock_telegram_bot_in_ban_bot: AsyncMock
):
    with unittest_patch('ban_bot.ban_bot.check_spam', new_callable=AsyncMock) as mock_check_spam:
        mock_check_spam.return_value = (False, "Reason: It's a normal message.\nVerdict: No")

        webhook_payload = {
            "update_id": 10001,
            "message": {
                "message_id": 102,
                "chat": {"id": 54321, "type": "private"},
                "from": {"id": 98765, "is_bot": False, "first_name": "JohnDoe"},
                "date": 1678886401,
                "text": "Hello world"
            }
        }

        response = ban_bot_client.post(BASE_SPAM_URL, json=webhook_payload)

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "is_spam": False}

        mock_check_spam.assert_called_once_with("Hello world")

        mock_telegram_bot_in_ban_bot.ban_chat_member.assert_not_called()
        mock_telegram_bot_in_ban_bot.send_message.assert_not_called()
        mock_telegram_bot_in_ban_bot.delete_message.assert_not_called()

@pytest.mark.asyncio
async def test_ban_bot_router_no_text_message(
    ban_bot_client: FastAPITestClient,
    mock_telegram_bot_in_ban_bot: AsyncMock
):
    with unittest_patch('ban_bot.ban_bot.check_spam', new_callable=AsyncMock) as mock_check_spam:
        # Configure check_spam to return False for empty string, as per current logic
        mock_check_spam.return_value = (False, "Reason: Empty message.\nVerdict: No")

        webhook_payload = {
            "update_id": 10002,
            "message": {
                "message_id": 103,
                "chat": {"id": 11223, "type": "group"},
                "from": {"id": 33445, "is_bot": False, "first_name": "MediaSender"},
                "date": 1678886402,
                "photo": [] # Indicates a photo message, text is None
            }
        }

        response = ban_bot_client.post(BASE_SPAM_URL, json=webhook_payload)

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "is_spam": False}

        mock_check_spam.assert_called_once_with("")

        mock_telegram_bot_in_ban_bot.ban_chat_member.assert_not_called()
        mock_telegram_bot_in_ban_bot.send_message.assert_not_called()
        mock_telegram_bot_in_ban_bot.delete_message.assert_not_called()
