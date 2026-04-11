import asyncio
import html
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from loguru import logger
from openai import AsyncOpenAI
from youtube_transcript_api import NoTranscriptFound

from ban_bot.ban_bot import router as ban_bot_router
from news_scheduler import NewsScheduler
from repository import Message, MessageRepository
from schemas import TelegramMessage, TelegramRequest
from settings import Settings
from summarizer import summary_url
from telegram import TelegramBot
from utils import create_verify_token_function, filter_context_size
from video_translator import translate_media
from youtube import get_transcript_summary
from youtube_transcript import process_youtube_transcript

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



telegram_bot = TelegramBot(
    settings.telegram_token,
    local_api_url=settings.telegram_local_api_url,
)

message_repository = MessageRepository()

openai = AsyncOpenAI(api_key=settings.openai_api_key)

news_scheduler = NewsScheduler(telegram_bot, settings)


async def handle_echo(chat_id, matched):
    logger.info(f"Received /echo command with message: {matched}")
    await telegram_bot.send_message(chat_id, f"Received your message: {matched}")


async def handle_start(chat_id):
    logger.info("Received /start command")
    message = (
        "echo - Echo your message\n"
        "summary - Summarize text\n"
        "summary_url - Summarize article from URL\n"
        "summary_youtube - Summarize YouTube video\n"
        "sy - Summarize YouTube video (shortcut)\n"
        "youtube_transcript - Get transcript with Telegraph pages\n"
        "yt - Get transcript with Telegraph pages (shortcut)\n"
        "prompt - Direct OpenAI prompt\n"
        "\n"
        "Forward any video, voice message, or round video-note to me "
        "and I'll translate it to English. If there are multiple speakers, "
        "I'll label them."
    )
    await telegram_bot.send_message(chat_id, message)


async def handle_summary_youtube(chat_id, matched):
    logger.info(f"Received /summary_url command with URL: {matched}")
    url = re.search(r"(https?://[^\s]+)", matched).group(0)
    summary_text = await asyncio.to_thread(get_transcript_summary, url)
    await telegram_bot.send_message(chat_id, f"Summary {url}:\n\n{summary_text}")


async def handle_youtube_transcript(chat_id, matched):
    """Handler for /youtube_transcript command"""
    logger.info(f"Received /youtube_transcript command with URL: {matched}")

    try:
        url = re.search(r"(https?://[^\s]+)", matched).group(0)

        await telegram_bot.send_message(chat_id, "🎬 Processing YouTube video...")

        result = await process_youtube_transcript(url)

        # Format response
        video_id = result['video_id']
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        message_parts = [
            f"<b>YouTube Transcription Complete</b> (Video: {video_id})",
            f"🔗 <a href=\"{youtube_url}\">YouTube Link</a>",
            f"Original Language: {result['original_language']}"
        ]

        transcript_urls = result.get('transcript_urls', [])
        if len(transcript_urls) == 1:
            message_parts.append(f"📄 <a href=\"{transcript_urls[0]}\">Full Transcript</a>")
        elif len(transcript_urls) > 1:
            for i, t_url in enumerate(transcript_urls, 1):
                message_parts.append(f"📄 <a href=\"{t_url}\">Transcript Part {i}</a>")
        if result.get('summary_url'):
            message_parts.append(f"📝 <a href=\"{result['summary_url']}\">Summary</a>")

        message_parts.append(f"\n<b>Summary:</b>\n{result['summary_text']}")

        await telegram_bot.send_message(chat_id, "\n".join(message_parts), parse_mode="HTML")

    except NoTranscriptFound:
        await telegram_bot.send_message(chat_id, "❌ No transcript available for this video.")
    except Exception as e:
        logger.error(f"Error in youtube_transcript: {e}")
        await telegram_bot.send_message(chat_id, f"❌ Error: {str(e)}")


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


_SPEAKER_LABEL_RE = re.compile(r"(?m)^Speaker\s+(\d+):")


def _render_translation_body(text: str) -> str:
    escaped = html.escape(text)
    return _SPEAKER_LABEL_RE.sub(r"<b>Speaker \1:</b>", escaped)


def _source_link_html(msg: TelegramMessage) -> str | None:
    """Build an HTML anchor pointing at the original message, if it can be linked publicly.

    Works for forwards from public channels (uses forward_origin.chat.username +
    message_id). Returns None for direct uploads, private chats, or hidden users.
    The anchor survives forwarding the translation message itself, so readers can
    still click through to the source.
    """
    fo = msg.forward_origin
    if not fo or fo.type != "channel" or not fo.chat or not fo.chat.username or not fo.message_id:
        return None
    url = f"https://t.me/{fo.chat.username}/{fo.message_id}"
    label = html.escape(fo.chat.title or fo.chat.username)
    return f'🔗 <a href="{html.escape(url, quote=True)}">{label}</a>'


async def handle_translate_video(msg: TelegramMessage):
    chat_id = msg.chat.id
    media = msg.video or msg.video_note or msg.voice
    logger.info(f"Received media for translation: chat_id={chat_id} file_id={media.file_id} size={media.file_size}")

    # Sanity cap only — the real effective ceiling is OpenAI's 25 MB post-transcode
    # mp3 limit (~50 minutes of audio). Larger files should be split by the sender.
    _max_bytes = 500 * 1024 * 1024
    if media.file_size and media.file_size > _max_bytes:
        await telegram_bot.send_message(
            chat_id,
            f"❌ File too large (>{_max_bytes // (1024 * 1024)} MB). Please split it.",
        )
        return

    await telegram_bot.send_message(chat_id, "🎧 Translating to English...")
    try:
        file_info = await telegram_bot.get_file(media.file_id)
        file_bytes = await telegram_bot.download_file(file_info["file_path"])
        filename = file_info["file_path"].rsplit("/", 1)[-1]
        result = await translate_media(file_bytes, filename, openai, settings)
    except Exception as e:
        logger.exception("translate_video failed")
        await telegram_bot.send_message(chat_id, f"❌ Error: {e}")
        return

    if result.source_lang:
        header = f"<b>English translation</b> <i>(from {result.source_lang}, path: {result.path_used})</i>"
    else:
        header = f"<b>English translation</b> <i>(path: {result.path_used})</i>"

    source_line = _source_link_html(msg)
    if source_line:
        header = f"{header}\n{source_line}"

    body = _render_translation_body(result.translated_text)
    if result.original_text:
        body = (
            f"<b>Original:</b>\n{html.escape(result.original_text)}\n\n"
            f"<b>Translation:</b>\n{body}"
        )

    await telegram_bot.send_message(chat_id, f"{header}\n\n{body}", parse_mode="HTML")


async def handle_message(request: TelegramRequest):
    msg = request.message
    chat_id = msg.chat.id

    if msg.video or msg.video_note or msg.voice:
        if msg.chat.type == "private":
            await handle_translate_video(msg)
        return

    text = msg.text
    if text is None:
        return

    if text.startswith("/echo"):
        matched = re.match(r"/echo (.+)", text).group(1)
        await handle_echo(chat_id, matched)
    elif text == "/start":
        await handle_start(chat_id)
    elif text.startswith("/summary_url"):
        matched = re.match(r"/summary_url (.+)", text).group(1)
        await handle_summary_url(chat_id, matched)
    elif text.startswith("/yt"):
        matched = re.match(r"/yt (.+)", text).group(1)
        await handle_youtube_transcript(chat_id, matched)
    elif text.startswith("/youtube_transcript"):
        matched = re.match(r"/youtube_transcript (.+)", text).group(1)
        await handle_youtube_transcript(chat_id, matched)
    elif text.startswith("/sy"):
        matched = re.match(r"/sy (.+)", text).group(1)
        await handle_summary_youtube(chat_id, matched)
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
