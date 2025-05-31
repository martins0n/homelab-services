import pytest
from fastapi.testclient import TestClient as FastAPITestClient # main_app_client fixture returns this
from unittest.mock import AsyncMock, patch as unittest_patch, MagicMock
import json
import asyncio # For asyncio.sleep
import time # For generate_unique_chat_id

# Assuming main_fastapi_app is imported for settings access, or use test_settings from fixture
from app import app as main_fastapi_app
from repository import MessageRepository # For type hinting if needed

# Default chat_id for most tests, can be overridden
TEST_CHAT_ID = 78901

# Sample Telegram request structure (can be expanded in tests)
def create_telegram_request_json(text: str, chat_id: int = TEST_CHAT_ID, from_user_id: int = 123, message_id: int = 100):
    return {
        "update_id": 10000,
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": from_user_id, "is_bot": False, "first_name": "TestUser"}, # Corrected: "from_user" back to "from"
            "date": 1678886400, # Timestamp
            "text": text
        }
    }

@pytest.mark.asyncio
async def test_health_endpoint(main_app_client: FastAPITestClient):
    response = main_app_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_api_health_endpoint(main_app_client: FastAPITestClient):
    with unittest_patch('app.message_repository.ping', new_callable=AsyncMock) as mock_ping:
        mock_ping.return_value = [{"created_at": "2023-01-01T12:00:00+00:00"}]

        response = main_app_client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == [{"created_at": "2023-01-01T12:00:00+00:00"}]
        mock_ping.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_handle_start(main_app_client: FastAPITestClient, mock_main_telegram_bot: AsyncMock):
    payload = create_telegram_request_json(text="/start")
    response = main_app_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    await asyncio.sleep(0.01)

    mock_main_telegram_bot.send_message.assert_called_once_with(
        TEST_CHAT_ID, "Hello! I'm a bot. Send me a message and I'll echo it back to you."
    )

@pytest.mark.asyncio
async def test_webhook_handle_echo(main_app_client: FastAPITestClient, mock_main_telegram_bot: AsyncMock):
    echo_text = "this is a test echo"
    payload = create_telegram_request_json(text=f"/echo {echo_text}")
    response = main_app_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    await asyncio.sleep(0.01)

    mock_main_telegram_bot.send_message.assert_called_once_with(
        TEST_CHAT_ID, f"Received your message: {echo_text}"
    )

# Added tests begin here

@pytest.mark.asyncio
async def test_webhook_handle_summary(
    main_app_client: FastAPITestClient,
    mock_main_telegram_bot: AsyncMock,
    mock_main_openai_completions_create: AsyncMock
):
    summary_text = "This is a test summary."
    input_text = "Please summarize this long text."
    # Simulate the structure of OpenAIObject that has .choices[0].message.content
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.content = summary_text
    mock_choice.message = mock_message
    mock_main_openai_completions_create.return_value = MagicMock(choices=[mock_choice])

    payload = create_telegram_request_json(text=f"/summary {input_text}")
    response = main_app_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    await asyncio.sleep(0.01)

    mock_main_openai_completions_create.assert_called_once()
    called_args, called_kwargs = mock_main_openai_completions_create.call_args
    assert called_kwargs['model'] == main_fastapi_app.settings.model
    assert called_kwargs['messages'][0]['role'] == 'user'
    assert f"Make a summary of the following text:\n\n{input_text}\n\n" in called_kwargs['messages'][0]['content']

    mock_main_telegram_bot.send_message.assert_called_once_with(TEST_CHAT_ID, summary_text)

@pytest.mark.asyncio
async def test_webhook_handle_summary_url(
    main_app_client: FastAPITestClient,
    mock_main_telegram_bot: AsyncMock
):
    url_to_summarize = "http://example.com/article"
    expected_summary = "This is the summary of the article."

    from summarizer import summary_url as actual_summary_url_func # Import for assertion
    with unittest_patch('app.asyncio.to_thread', new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = expected_summary

        payload = create_telegram_request_json(text=f"/summary_url {url_to_summarize}")
        response = main_app_client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        await asyncio.sleep(0.01)

        mock_to_thread.assert_called_once_with(actual_summary_url_func, url_to_summarize)

        mock_main_telegram_bot.send_message.assert_called_once_with(
            TEST_CHAT_ID, f"Summary:\n\n{expected_summary}"
        )

@pytest.mark.asyncio
async def test_webhook_handle_summary_youtube(
    main_app_client: FastAPITestClient,
    mock_main_telegram_bot: AsyncMock
):
    youtube_url = "http://youtube.com/watch?v=dQw4w9WgXcQ"
    expected_transcript_summary = "Summary of the YouTube video."

    from youtube import get_transcript_summary as actual_yt_summary_func # Import for assertion
    with unittest_patch('app.asyncio.to_thread', new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = expected_transcript_summary

        payload = create_telegram_request_json(text=f"/summary_youtube {youtube_url}")
        response = main_app_client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        await asyncio.sleep(0.01)

        mock_to_thread.assert_called_once_with(actual_yt_summary_func, youtube_url)

        mock_main_telegram_bot.send_message.assert_called_once_with(
            TEST_CHAT_ID, f"Summary {youtube_url}:\n\n{expected_transcript_summary}"
        )

@pytest.mark.asyncio
async def test_webhook_handle_prompt(
    main_app_client: FastAPITestClient,
    mock_main_telegram_bot: AsyncMock,
    mock_main_openai_completions_create: AsyncMock
):
    prompt_text = "What is the meaning of life?"
    gpt_response_text = "42, or so I've heard."
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.content = gpt_response_text
    mock_choice.message = mock_message
    mock_main_openai_completions_create.return_value = MagicMock(choices=[mock_choice])

    payload = create_telegram_request_json(text=f"/prompt {prompt_text}")
    response = main_app_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    await asyncio.sleep(0.01)

    mock_main_openai_completions_create.assert_called_once()
    called_args, called_kwargs = mock_main_openai_completions_create.call_args
    assert called_kwargs['model'] == main_fastapi_app.settings.model
    assert called_kwargs['messages'][0]['role'] == 'user'
    assert called_kwargs['messages'][0]['content'] == prompt_text

    mock_main_telegram_bot.send_message.assert_called_once_with(TEST_CHAT_ID, gpt_response_text)

@pytest.mark.asyncio
async def test_webhook_handle_no_such_command(
    main_app_client: FastAPITestClient,
    mock_main_telegram_bot: AsyncMock
):
    command_name = "nonexistentcommand"
    payload = create_telegram_request_json(text=f"/{command_name}")
    response = main_app_client.post("/webhook", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    await asyncio.sleep(0.01)

    mock_main_telegram_bot.send_message.assert_called_once_with(
        TEST_CHAT_ID, f"No such command: {command_name}"
    )

@pytest.mark.asyncio
async def test_webhook_handle_default_message(
    main_app_client: FastAPITestClient,
    app_message_repo: MessageRepository,
    mock_main_telegram_bot: AsyncMock,
    mock_main_openai_completions_create: AsyncMock
):
    user_message_text = "This is a general user message."
    assistant_response_text = "This is the assistant's reply."

    mock_choice = MagicMock()
    mock_message_content = MagicMock()
    mock_message_content.content = assistant_response_text
    mock_choice.message = mock_message_content
    mock_main_openai_completions_create.return_value = MagicMock(choices=[mock_choice])

    with unittest_patch.object(app_message_repo, 'get_messages', new_callable=AsyncMock) as mock_get_messages, \
         unittest_patch.object(app_message_repo, 'add_messages', new_callable=AsyncMock) as mock_add_messages:

        mock_get_messages.return_value = []

        payload = create_telegram_request_json(text=user_message_text, chat_id=TEST_CHAT_ID)
        response = main_app_client.post("/webhook", json=payload)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        await asyncio.sleep(0.05)

        mock_get_messages.assert_called_once_with(TEST_CHAT_ID)

        mock_main_openai_completions_create.assert_called_once()
        _, called_kwargs = mock_main_openai_completions_create.call_args
        assert len(called_kwargs['messages']) == 1
        assert called_kwargs['messages'][0]['role'] == 'user'
        assert called_kwargs['messages'][0]['content'] == user_message_text

        mock_main_telegram_bot.send_message.assert_called_once_with(TEST_CHAT_ID, assistant_response_text)

        assert mock_add_messages.call_count == 2
        args_user, _ = mock_add_messages.call_args_list[0]
        assert args_user[0] == TEST_CHAT_ID
        assert len(args_user[1]) == 1
        assert args_user[1][0].content == user_message_text # Changed to attribute access
        assert args_user[1][0].user == 'user'

        args_assistant, _ = mock_add_messages.call_args_list[1]
        assert args_assistant[0] == TEST_CHAT_ID
        assert len(args_assistant[1]) == 1
        assert args_assistant[1][0].content == assistant_response_text # Changed to attribute access
        assert args_assistant[1][0].user == 'assistant'

def generate_unique_chat_id() -> int: # Defined locally as planned
    return int(time.time() * 1000)
