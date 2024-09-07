import asyncio
import re
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from loguru import logger
from openai import AsyncOpenAI

from repository import Message, MessageRepository
from schemas import TelegramMessage, TelegramRequest
from settings import Settings
from telegram import TelegramBot
from utils import filter_context_size

settings = Settings()

app = FastAPI()


async def verify_token(x_telegram_bot_api_secret_token: Annotated[str, Header()]):
    if x_telegram_bot_api_secret_token != settings.x_telegram_bot_header:
        raise HTTPException(status_code=200, detail="Invalid token")


telegram_bot = TelegramBot(settings.telegram_token)

message_repository = MessageRepository()

openai = AsyncOpenAI(api_key=settings.openai_api_key)


async def handle_echo(chat_id, matched):
    logger.info(f"Received /echo command with message: {matched}")
    await telegram_bot.send_message(chat_id, f"Received your message: {matched}")


async def handle_start(chat_id):
    logger.info("Received /start command")
    await telegram_bot.send_message(
        chat_id, "Hello! I'm a bot. Send me a message and I'll echo it back to you."
    )


async def handle_default(msg: TelegramMessage):
    logger.info(f"Received default message: {msg.text}")
    chat_id = msg.chat.id
    messages = await message_repository.get_messages(chat_id)

    new_message = Message(**{"content": msg.text, "user": "user"})
    messages.append(new_message)

    messages_to_send = filter_context_size(
        [{"role": m.user, "content": m.content} for m in messages],
        settings.context_size,
        settings.model,
    )

    logger.info(f"Messages to send: {messages_to_send}")
    response = await openai.chat.completions.create(
        model=settings.model, messages=messages_to_send
    )
    logger.info(f"Response: {response}")
    answer = response.choices[0].message.content

    logger.info(f"Responding with: {response}")

    await telegram_bot.send_message(chat_id, answer)

    logger.info("Adding messages to repository")

    await message_repository.add_messages(
        chat_id,
        [
            {"content": msg.text, "user": "user"},
        ],
    )

    await message_repository.add_messages(
        chat_id,
        [
            {"content": answer, "user": "assistant"},
        ],
    )

    logger.info("Added messages to repository")


async def handle_summary(chat_id, matched):
    logger.info(f"Received /summary command with text: {matched}")
    response = await openai.chat.completions.create(
        model=settings.model,
        messages=[
            {
                "role": "user",
                "content": f"Make a summary of the following text:\n\n{matched}\n\n",
            }
        ],
    )
    summary = response.choices[0].message.content
    await telegram_bot.send_message(chat_id, summary)


async def handle_summary_url(chat_id, matched):
    logger.info(f"Received /summary_url command with URL: {matched}")
    url = re.search(r"(https?://[^\s]+)", matched).group(0)

    async with httpx.AsyncClient() as client:
        await client.post(
            settings.summary_queue_url,
            json={"url": url, "chat_id": chat_id},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Api-Key {settings.ya_api}",
            },
        )


async def handle_prompt(chat_id, matched):
    logger.info(f"Received /prompt command with text: {matched}")
    response = await openai.chat.completions.create(
        model=settings.model, messages=[{"role": "user", "content": matched}]
    )
    logger.info(f"Prompt response: {response}")
    prompt_response = response.choices[0].message.content
    await telegram_bot.send_message(chat_id, prompt_response)


async def handle_message(request: TelegramRequest):
    msg = request.message
    chat_id = msg.chat.id
    text = msg.text

    if text.startswith("/echo"):
        matched = re.match(r"/echo (.+)", text).group(1)
        await handle_echo(chat_id, matched)
    elif text == "/start":
        await handle_start(chat_id)
    elif text.startswith("/summary_url"):
        matched = re.match(r"/summary_url (.+)", text).group(1)
        await handle_summary_url(chat_id, matched)
    elif text.startswith("/summary"):
        matched = re.match(r"/summary (.+)", text).group(1)
        await handle_summary(chat_id, matched)
    elif text.startswith("/prompt"):
        matched = re.match(r"/prompt (.+)", text).group(1)
        await handle_prompt(chat_id, matched)
    else:
        await handle_default(msg)


if settings.env == "prod":
    dependencies = [Depends(verify_token)]
else:
    dependencies = []


@app.post("/webhook", dependencies=dependencies)
async def webhook(request: TelegramRequest):
    asyncio.create_task(handle_message(request))
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/ping")
async def ping():
    return await message_repository.ping()
