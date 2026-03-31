from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from httpx import AsyncClient
from loguru import logger

from ban_bot.gpt import check_spam
from schemas import TelegramRequest
from settings import Settings
from utils import create_verify_token_function

settings = Settings()

user_call_log = defaultdict(list)

def can_call(user_id, max_calls, time_period):
    current_time = datetime.now()
    call_times = user_call_log[user_id]

    call_times = [t for t in call_times if current_time - t < timedelta(seconds=time_period)]

    user_call_log[user_id] = call_times

    if len(call_times) < max_calls:
        user_call_log[user_id].append(current_time)
        return True
    else:
        return False



router = APIRouter(prefix="/ban_bot")


verify_token = create_verify_token_function(settings.x_telegram_spam_bot_header)

if settings.env == "prod":
    dependencies = [Depends(verify_token)]
else:
    dependencies = []

async def handle_message(r: Request):
    logger.info(f"Received request: {r}")
    msg = TelegramRequest(**r)
    message = msg.message

    # Collect all text content for spam scoring
    parts = []
    if message.text:
        parts.append(message.text)
    if message.caption:
        parts.append(message.caption)
    if message.quote and message.quote.text:
        parts.append(message.quote.text)

    # Extract URLs from text_link entities (hidden links)
    for entity_list in [message.entities, message.caption_entities]:
        if entity_list:
            for e in entity_list:
                if e.type == "text_link" and e.url:
                    parts.append(e.url)

    combined_text = "\n".join(parts)
    if not combined_text:
        return

    chat_id = message.chat.id
    if not can_call(chat_id, 10, 60):
        logger.info(f"Too many calls from {chat_id}")
        return

    is_spam, reason = await check_spam(combined_text)
    logger.info(f"Is spam: {is_spam}, reason: {reason}, user: {message.from_}")
    if is_spam:
        async with AsyncClient(timeout=60) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.telegram_spam_bot_token}/deleteMessage",
                data={"chat_id": message.chat.id, "message_id": message.message_id}
            )
            await client.post(
                f"https://api.telegram.org/bot{settings.telegram_spam_bot_token}/banChatMember",
                data={"chat_id": message.chat.id, "user_id": message.from_.id, "revoke_messages": True}
            )


@router.post("/webhook", dependencies=dependencies)
async def webhook(request: Request):
    r = await request.json()
    try:
        await handle_message(r)
    except Exception as e:
        logger.error(f"Error: {e}")
    return {"status": "ok"}