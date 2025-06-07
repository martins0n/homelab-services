import asyncio
import pytest
import httpx
@pytest.mark.asyncio
async def test_health(test_app):
    app, _, _ = test_app
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_webhook_echo(test_app):
    app, repo, calls = test_app
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": 123, "is_bot": False},
            "chat": {"id": 123, "type": "private"},
            "date": 0,
            "text": "/echo hello",
        },
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    await asyncio.sleep(0.05)
    assert calls[0] == (123, "Received your message: hello")

@pytest.mark.asyncio
async def test_webhook_default_message(test_app):
    app, repo, calls = test_app
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": 123, "is_bot": False},
            "chat": {"id": 123, "type": "private"},
            "date": 0,
            "text": "hi",
        },
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    await asyncio.sleep(0.05)
    assert calls[0] == (123, "answer")
    assert repo.storage[123][0].content == "hi"
