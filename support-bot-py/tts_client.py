"""Client for the ml-service /tts endpoint.

Turns a list of {voice, text} segments into spoken audio (mp3 bytes) so the bot
can read translated transcripts aloud and send them as a Telegram audio message —
Android Chrome's "Read Aloud" doesn't work on Telegraph pages, so synthesized
audio played inside Telegram is the workaround.

Shared by the plain-transcript and diarized paths; kept in its own module to avoid
a circular import (youtube_diarize already imports youtube_transcript)."""
import httpx
import json

from loguru import logger

from settings import Settings

# Piper en_US voice pool, alternating female/male. Diarized transcripts assign
# Speaker 1..N -> pool[(n-1) % len(pool)] so each speaker gets a distinct voice
# (round-robin if there are more speakers than voices). Plain transcripts use the
# first voice as a single narrator.
VOICE_POOL = ["amy", "ryan", "kathleen", "lessac"]


def voice_for_speaker(n: int) -> str:
    """Map a 1-based speaker number to a pool voice (round-robin)."""
    return VOICE_POOL[(n - 1) % len(VOICE_POOL)]


async def synthesize_segments(
    segments: list[dict], settings: Settings, speed: float | None = None
) -> bytes | None:
    """POST [{voice,text}] segments to ml-service /tts; return mp3 bytes or None.

    Never raises — TTS is a best-effort extra on top of the text transcript, so a
    failure here must not break the reply. A generous read timeout covers long
    transcripts (Piper RTF ~0.1 on the Pi, plus ffmpeg)."""
    segments = [s for s in segments if (s.get("text") or "").strip()]
    if not segments:
        return None
    endpoint = settings.ml_service_url.rstrip("/") + "/tts"
    data = {"segments": json.dumps(segments, ensure_ascii=False)}
    if speed is not None:
        data["speed"] = str(speed)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=15.0)) as client:
            r = await client.post(endpoint, data=data)
            r.raise_for_status()
            audio = r.content
            logger.info(f"tts: synthesized {len(audio)} bytes from {len(segments)} segments")
            return audio or None
    except Exception as e:
        logger.error(f"tts: synthesis failed: {e!r}")
        return None
