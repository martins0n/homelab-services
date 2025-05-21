import httpx
import pytest
from fastapi.testclient import TestClient
from respx.router import Router
from unittest.mock import patch, AsyncMock, call

from .conftest import send_telegram_message
from support_bot_py.settings import Settings # For type hinting test_settings
from support_bot_py.repository import Message # For constructing expected messages

def test_handle_start_command(
    client: TestClient, respx_router: Router, test_settings: Settings
):
    """Tests the /start command handler."""
    mock_route = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    response = send_telegram_message(client, "/start", chat_id=123)

    assert response.status_code == 200
    assert mock_route.called
    assert mock_route.call_count == 1
    
    expected_payload = {
        "chat_id": 123,
        "text": "Hello! I'm a bot. Send me a message and I'll echo it back to you.",
    }
    assert mock_route.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_payload
    ).content


def test_health_endpoint(client: TestClient):
    """Tests the /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch('support_bot_py.app.message_repository.ping', new_callable=AsyncMock)
async def test_api_health_endpoint(mock_ping: AsyncMock, client: TestClient):
    """Tests the /api/health endpoint."""
    mock_ping.return_value = True # Mocking the successful ping from the database

    response = client.get("/api/health") # TestClient handles async nature of endpoint

    assert response.status_code == 200
    mock_ping.assert_awaited_once()
    assert response.json() == True


@patch('support_bot_py.app.message_repository.add_messages', new_callable=AsyncMock)
@patch('support_bot_py.app.message_repository.get_messages', new_callable=AsyncMock)
def test_handle_default_message(
    mock_get_messages: AsyncMock,
    mock_add_messages: AsyncMock,
    client: TestClient,
    respx_router: Router,
    test_settings: Settings,
):
    """Tests the default message handler for non-command messages."""
    regular_message_text = "Just a regular message."
    chat_id = 303
    user_id = 606 # example user_id
    expected_ai_response = "This is a default AI response."

    # Configure mocks
    mock_get_messages.return_value = [] # No previous messages

    # Mock Telegram API
    telegram_mock = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    # Mock OpenAI API
    openai_mock = respx_router.post(
        "https://api.openai.com/v1/chat/completions"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-test-default",
                "object": "chat.completion",
                "created": 1677652290,
                "model": test_settings.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": expected_ai_response},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )
    )

    # Send the message
    response = send_telegram_message(client, regular_message_text, chat_id=chat_id, user_id=user_id)

    # Assertions
    assert response.status_code == 200

    # Assert get_messages was called
    mock_get_messages.assert_awaited_once_with(str(chat_id))

    # Assert OpenAI API call
    assert openai_mock.called
    assert openai_mock.call_count == 1
    expected_openai_payload_messages = [
        {"role": "user", "content": regular_message_text} # Only user message as context is empty
    ]
    actual_openai_payload = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        json=openai_mock.calls.last.request.content.decode()
    ).json()
    assert actual_openai_payload["model"] == test_settings.model
    assert actual_openai_payload["messages"] == expected_openai_payload_messages

    # Assert Telegram API sendMessage call
    assert telegram_mock.called
    assert telegram_mock.call_count == 1
    expected_telegram_payload = {
        "chat_id": chat_id,
        "text": expected_ai_response,
    }
    assert telegram_mock.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_telegram_payload
    ).content

    # Assert add_messages calls
    assert mock_add_messages.await_count == 2 # Corrected: await_count for AsyncMock

    # Verify the first call (user's message)
    # The app.py uses dicts: [{'content': msg.text, 'user': 'user'}]
    expected_first_add_messages_arg = [
        Message(chat_id=str(chat_id), user_id=str(user_id), content=regular_message_text, user_role="user").model_dump(exclude_none=True, exclude={'timestamp', 'id'})
    ]
    # Convert the actual call's Message objects to dicts for comparison as app.py stores dicts
    actual_first_call_args = [msg.model_dump(exclude_none=True, exclude={'timestamp', 'id'}) for msg in mock_add_messages.await_args_list[0][0][0]]
    assert actual_first_call_args[0]['chat_id'] == str(chat_id)
    assert actual_first_call_args[0]['user_id'] == str(user_id)
    assert actual_first_call_args[0]['content'] == regular_message_text
    assert actual_first_call_args[0]['user_role'] == 'user'


    # Verify the second call (assistant's response)
    expected_second_add_messages_arg = [
         Message(chat_id=str(chat_id), user_id="assistant", content=expected_ai_response, user_role="assistant").model_dump(exclude_none=True, exclude={'timestamp', 'id'})
    ]
    actual_second_call_args = [msg.model_dump(exclude_none=True, exclude={'timestamp', 'id'}) for msg in mock_add_messages.await_args_list[1][0][0]]
    assert actual_second_call_args[0]['chat_id'] == str(chat_id)
    assert actual_second_call_args[0]['user_id'] == 'assistant' # In app.py user_id for assistant is set to "assistant"
    assert actual_second_call_args[0]['content'] == expected_ai_response
    assert actual_second_call_args[0]['user_role'] == 'assistant'


def test_handle_prompt_command(
    client: TestClient, respx_router: Router, test_settings: Settings
):
    """Tests the /prompt command handler."""
    prompt_text = "What is the meaning of life?"
    expected_response_text = "This is a test prompt response."

    # Mock Telegram API
    telegram_mock = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    # Mock OpenAI API
    openai_mock = respx_router.post(
        "https://api.openai.com/v1/chat/completions"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-test-prompt",
                "object": "chat.completion",
                "created": 1677652289,
                "model": test_settings.model, # Using the general model
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": expected_response_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )
    )

    response = send_telegram_message(
        client, f"/prompt {prompt_text}", chat_id=101
    )

    assert response.status_code == 200
    assert telegram_mock.called
    assert telegram_mock.call_count == 1
    assert openai_mock.called
    assert openai_mock.call_count == 1

    # Check Telegram payload
    expected_telegram_payload = {
        "chat_id": 101,
        "text": expected_response_text,
    }
    assert telegram_mock.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_telegram_payload
    ).content

    # Check OpenAI payload
    expected_openai_messages = [
        {"role": "system", "content": "You are a helpful assistant."}, # Default system prompt
        {"role": "user", "content": prompt_text},
    ]
    actual_openai_payload = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        json=openai_mock.calls.last.request.content.decode() # content is bytes
    ).json()

    assert actual_openai_payload["model"] == test_settings.model
    assert actual_openai_payload["messages"] == expected_openai_messages


def test_handle_unknown_command(
    client: TestClient, respx_router: Router, test_settings: Settings
):
    """Tests the handler for unknown commands."""
    unknown_command_text = "/foobar"

    # Mock Telegram API
    telegram_mock = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))
    
    # We are not mocking OpenAI here, as it should not be called.
    # respx_router has assert_all_called=False, so no issues with uncalled routes.

    response = send_telegram_message(client, unknown_command_text, chat_id=202)

    assert response.status_code == 200
    assert telegram_mock.called
    assert telegram_mock.call_count == 1

    # Check Telegram payload
    expected_telegram_payload = {
        "chat_id": 202,
        "text": "No such command: foobar", # Command name extracted from /foobar
    }
    assert telegram_mock.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_telegram_payload
    ).content

    # Check that OpenAI was not called
    openai_route = respx_router["https://api.openai.com/v1/chat/completions"]
    assert not openai_route.called


def test_handle_summary_command(
    client: TestClient, respx_router: Router, test_settings: Settings
):
    """Tests the /summary command handler."""
    text_to_summarize = "This is a long text to be summarized."
    expected_summary = "This is a test summary."

    # Mock Telegram API
    telegram_mock = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    # Mock OpenAI API
    openai_mock = respx_router.post(
        "https://api.openai.com/v1/chat/completions"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1677652288,
                "model": "gpt-3.5-turbo-0125",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": expected_summary},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
            },
        )
    )

    response = send_telegram_message(
        client, f"/summary {text_to_summarize}", chat_id=789
    )

    assert response.status_code == 200
    assert telegram_mock.called
    assert telegram_mock.call_count == 1
    assert openai_mock.called
    assert openai_mock.call_count == 1

    # Check Telegram payload
    expected_telegram_payload = {
        "chat_id": 789,
        "text": expected_summary,
    }
    assert telegram_mock.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_telegram_payload
    ).content

    # Check OpenAI payload
    expected_openai_messages = [
        {"role": "system", "content": "You are a helpful assistant that summarizes text."},
        {"role": "user", "content": f"Summarize the following text:\n\n{text_to_summarize}"},
    ]
    actual_openai_payload = httpx.Request(
        "POST",
        "https://api.openai.com/v1/chat/completions",
        json=openai_mock.calls.last.request.content.decode() # content is bytes
    ).json()


    assert actual_openai_payload["model"] == test_settings.model_summarizer # Corrected to model_summarizer
    assert actual_openai_payload["messages"] == expected_openai_messages


@patch('support_bot_py.app.app.summary_url', new_callable=AsyncMock)
def test_handle_summary_url_command(
    mocked_summary_url: AsyncMock,
    client: TestClient,
    respx_router: Router,
    test_settings: Settings,
):
    """Tests the /summary_url command handler."""
    url_to_summarize = "http://example.com/article"
    expected_summary = "Test URL summary."
    mocked_summary_url.return_value = expected_summary

    telegram_mock = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    response = send_telegram_message(
        client, f"/summary_url {url_to_summarize}", chat_id=789
    )

    assert response.status_code == 200
    mocked_summary_url.assert_awaited_once_with(url_to_summarize)
    assert telegram_mock.called
    
    expected_telegram_payload = {
        "chat_id": 789,
        "text": f"Summary:\n\n{expected_summary}",
    }
    assert telegram_mock.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_telegram_payload
    ).content


@patch('support_bot_py.app.app.get_transcript_summary', new_callable=AsyncMock)
def test_handle_summary_youtube_command(
    mocked_get_transcript_summary: AsyncMock,
    client: TestClient,
    respx_router: Router,
    test_settings: Settings,
):
    """Tests the /summary_youtube command handler."""
    youtube_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    expected_summary = "Test YouTube summary."
    mocked_get_transcript_summary.return_value = expected_summary

    telegram_mock = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    response = send_telegram_message(
        client, f"/summary_youtube {youtube_url}", chat_id=789
    )

    assert response.status_code == 200
    mocked_get_transcript_summary.assert_awaited_once_with(youtube_url)
    assert telegram_mock.called

    expected_telegram_payload = {
        "chat_id": 789,
        "text": f"Summary {youtube_url}:\n\n{expected_summary}",
    }
    assert telegram_mock.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_telegram_payload
    ).content


def test_handle_echo_command(
    client: TestClient, respx_router: Router, test_settings: Settings
):
    """Tests the /echo command handler."""
    message_to_echo = "Hello, world!"
    mock_route = respx_router.post(
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    response = send_telegram_message(
        client, f"/echo {message_to_echo}", chat_id=456
    )

    assert response.status_code == 200
    assert mock_route.called
    assert mock_route.call_count == 1

    expected_payload = {
        "chat_id": 456,
        "text": f"Received your message: {message_to_echo}",
    }
    assert mock_route.calls.last.request.content == httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{test_settings.telegram_token}/sendMessage",
        json=expected_payload
    ).content
