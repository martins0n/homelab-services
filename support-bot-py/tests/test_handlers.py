import json
from unittest.mock import patch

from tests.conftest import make_payload, wait_for_background_tasks


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_echo(client, telegram_mock):
    r = await client.post("/webhook", json=make_payload("/echo hello world"))
    assert r.json() == {"status": "ok"}
    await wait_for_background_tasks()
    assert telegram_mock.calls.last is not None
    sent = json.loads(telegram_mock.calls.last.request.content)
    assert "hello world" in sent["text"]
    assert sent["chat_id"] == 100


async def test_start(client, telegram_mock):
    await client.post("/webhook", json=make_payload("/start"))
    await wait_for_background_tasks()
    sent = json.loads(telegram_mock.calls.last.request.content)
    assert "echo" in sent["text"].lower()


async def test_unknown_command(client, telegram_mock):
    await client.post("/webhook", json=make_payload("/nonexistent"))
    await wait_for_background_tasks()
    sent = json.loads(telegram_mock.calls.last.request.content)
    assert "no such command" in sent["text"].lower()


async def test_summary(client, telegram_mock, openai_mock):
    await client.post("/webhook", json=make_payload("/summary some long text here"))
    await wait_for_background_tasks()
    sent = json.loads(telegram_mock.calls.last.request.content)
    assert sent["text"] == "mocked response"


async def test_default_chat(client, telegram_mock, openai_mock, supabase_mock):
    await client.post("/webhook", json=make_payload("hello bot"))
    await wait_for_background_tasks()
    # Verify Supabase history was fetched and Telegram received the reply
    supabase_mock["get"].assert_called_once()
    sent = json.loads(telegram_mock.calls.last.request.content)
    assert sent["text"] == "mocked response"


async def test_yt_no_transcript(client, telegram_mock):
    """YouTube URL where transcript API raises → bot sends error message."""
    with patch(
        "youtube_transcript.YouTubeTranscriptApi.list_transcripts",
        side_effect=Exception("no transcript available"),
    ):
        await client.post(
            "/webhook",
            json=make_payload("/yt https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        )
        await wait_for_background_tasks()
    sent = json.loads(telegram_mock.calls.last.request.content)
    assert "Error" in sent["text"]
