import asyncio
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from loguru import logger
from openai import AsyncOpenAI

from ban_bot.ban_bot import router as ban_bot_router
from news_scheduler import NewsScheduler
from repository import Message, MessageRepository
from schemas import TelegramMessage, TelegramRequest
from settings import Settings
from summarizer import summary_url
from telegram import TelegramBot
from utils import create_verify_token_function, filter_context_size
from youtube import get_transcript_summary

settings = Settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Manage application lifespan - startup and shutdown events"""
    # Startup
    logger.info("Starting news scheduler...")
    await news_scheduler.start()
    
    yield
    
    # Shutdown
    logger.info("Stopping news scheduler...")
    await news_scheduler.stop()


app = FastAPI(lifespan=lifespan)

app.include_router(ban_bot_router)



telegram_bot = TelegramBot(settings.telegram_token)

message_repository = MessageRepository()

openai = AsyncOpenAI(api_key=settings.openai_api_key)

news_scheduler = NewsScheduler(telegram_bot, settings)


async def handle_echo(chat_id, matched):
    logger.info(f"Received /echo command with message: {matched}")
    await telegram_bot.send_message(chat_id, f"Received your message: {matched}")


async def handle_start(chat_id):
    logger.info("Received /start command")
    message = (
        "Hello\\! I'm a support bot with the following commands:\n\n"
        "💬 *Regular chat* \\- just send me a message\n"
        "🔄 /echo \\<text\\> \\- echo your message\n\n"
        "📄 *Other Commands:*\n"
        "📝 /summary \\<text\\> \\- summarize text\n"
        "🌐 /summary\\_url \\<url\\> \\- summarize article from URL\n"
        "📺 /summary\\_youtube \\<url\\> \\- summarize YouTube video\n"
        "🤖 /prompt \\<text\\> \\- direct OpenAI prompt"
    )
    await telegram_bot.send_message(chat_id, message)


async def handle_summary_youtube(chat_id, matched):
    logger.info(f"Received /summary_url command with URL: {matched}")
    url = re.search(r"(https?://[^\s]+)", matched).group(0)
    summary_text = await asyncio.to_thread(get_transcript_summary, url)
    await telegram_bot.send_message(chat_id, f"Summary {url}:\n\n{summary_text}")


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


async def handle_no_such_command(chat_id, matched):
    logger.info(f"Received unknown command: {matched}")
    await telegram_bot.send_message(chat_id, f"No such command: {matched}")


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
    summary_text = await asyncio.to_thread(summary_url, url)
    await telegram_bot.send_message(chat_id, f"Summary:\n\n{summary_text}")


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
    elif text.startswith("/summary_youtube"):
        matched = re.match(r"/summary_youtube (.+)", text).group(1)
        await handle_summary_youtube(chat_id, matched)
    elif text.startswith("/summary"):
        matched = re.match(r"/summary (.+)", text).group(1)
        await handle_summary(chat_id, matched)
    elif text.startswith("/prompt"):
        matched = re.match(r"/prompt (.+)", text).group(1)
        await handle_prompt(chat_id, matched)
    elif text.startswith("/"):
        matched = re.match(r"/(.+)", text).group(1)
        await handle_no_such_command(chat_id, matched)
    else:
        await handle_default(msg)


verify_token = create_verify_token_function(settings.x_telegram_bot_header)

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


@app.get("/api/health")
async def ping():
    return await message_repository.ping()
