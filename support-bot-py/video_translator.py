import asyncio
import base64
import os
import shutil
import tempfile
from dataclasses import dataclass

import openai as openai_exc
from loguru import logger
from openai import AsyncOpenAI

from settings import Settings

_E2E_PROMPT = """\
Give me the English version of what is spoken in this audio. If the speakers are already using English, just write their words. If they are using any other language, express the meaning in English.

Formatting:
- If multiple people speak, begin each turn on a new line with "Speaker 1:", "Speaker 2:", etc., consistent by voice.
- If one person speaks, write plain English with no speaker labels.
- Begin your reply with the first spoken word. No introduction, no "Here is", no "Translation:", no quotation marks.
"""


_PREAMBLE_STRIPPERS = (
    "here is the english version",
    "here is the english translation",
    "here's the english version",
    "here's the english translation",
    "here is the transcription",
    "here is the content translated",
    "here is the translation",
    "here's the transcription",
    "translation:",
    "english translation:",
    "transcription:",
)


def _strip_preamble(text: str) -> str:
    """Defensively remove any 'Here is the translation:' style preamble and surrounding quotes."""
    if not text:
        return text
    stripped = text.strip()

    lines = stripped.split("\n", 1)
    first = lines[0].lower().strip().rstrip(":").rstrip(".")
    rest = lines[1] if len(lines) > 1 else ""
    if any(first.startswith(p.rstrip(":")) for p in _PREAMBLE_STRIPPERS):
        stripped = rest.lstrip()

    if len(stripped) >= 2 and stripped[0] in ('"', "'", "«") and stripped[-1] in ('"', "'", "»"):
        stripped = stripped[1:-1].strip()

    return stripped

_REFUSAL_PHRASES = (
    "i can't assist",
    "i cannot assist",
    "i'm unable to",
    "i am unable to",
    "i can't help",
    "i cannot help",
    "against my guidelines",
    "i'm sorry, but i can",
)


@dataclass
class TranslateResult:
    translated_text: str
    path_used: str  # "diarize" | "e2e" | "fallback"
    source_lang: str | None = None
    original_text: str | None = None


_DIARIZE_TRANSLATE_PROMPT = """\
You are given a diarized transcript where each line begins with a speaker label like "Speaker 1:" or "Speaker 2:".

Translate it to English. Keep every speaker label exactly as-is (same number, same "Speaker N:" format, one per line). Only the content after the label should be translated. If the content is already in English, keep it verbatim.

Output only the translated transcript, no preamble.
"""


def _format_diarized_segments(segments: list[dict]) -> str:
    """Merge consecutive same-speaker segments and format as 'Speaker N: text' lines.

    Normalizes whatever raw label the diarize model returns (e.g. 'A', 'B',
    'speaker_0') into 'Speaker 1', 'Speaker 2', etc., by first-appearance order.
    """
    if not segments:
        return ""
    label_map: dict[str, str] = {}
    merged: list[tuple[str, str]] = []
    for seg in segments:
        raw = seg.get("speaker") or "Speaker 1"
        if raw not in label_map:
            label_map[raw] = f"Speaker {len(label_map) + 1}"
        speaker = label_map[raw]
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if merged and merged[-1][0] == speaker:
            merged[-1] = (speaker, merged[-1][1] + " " + text)
        else:
            merged.append((speaker, text))
    return "\n".join(f"{sp}: {tx}" for sp, tx in merged)


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def _to_mp3(file_bytes: bytes, filename: str) -> bytes:
    """Transcode any audio/video to 16kHz mono mp3 via ffmpeg.

    gpt-4o-mini-audio-preview only accepts wav/mp3, and whisper-class endpoints
    have been observed to 500 on some Telegram mp4 files. Normalizing to mp3
    unblocks both paths.
    """
    if _ext(filename) == "mp3":
        return file_bytes
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not available on PATH — install ffmpeg to translate media")

    ext = _ext(filename) or "bin"
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as inf:
        inf.write(file_bytes)
        in_path = inf.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i", in_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ab", "64k",
            "-ar", "16000",
            "-ac", "1",
            "-f", "mp3",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            snippet = err.decode("utf-8", errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {snippet}")
        if not out:
            raise RuntimeError("ffmpeg produced empty output")
        return out
    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass


def _is_refusal(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(p in low for p in _REFUSAL_PHRASES)


async def _translate_diarize(
    mp3_bytes: bytes,
    openai_client: AsyncOpenAI,
    settings: Settings,
) -> tuple[str, str, str | None]:
    """Primary path: gpt-4o-transcribe-diarize gives speaker labels, then chat completion translates preserving labels.

    Returns (original_formatted, translated_formatted, source_lang).
    """
    resp = await openai_client.audio.transcriptions.create(
        model=settings.model_diarize,
        file=("audio.mp3", mp3_bytes),
        response_format="diarized_json",
        extra_body={"chunking_strategy": "auto"},
    )

    # Response is either pydantic-ish or dict-like; normalize.
    raw = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
    segments = raw.get("segments") or []
    source_lang = raw.get("language")

    if not segments:
        raise RuntimeError("diarize returned no segments")

    original_formatted = _format_diarized_segments(segments)
    if not original_formatted:
        raise RuntimeError("diarize segments had no text")

    translate_resp = await openai_client.chat.completions.create(
        model=settings.model_transcript,
        messages=[
            {"role": "system", "content": _DIARIZE_TRANSLATE_PROMPT},
            {"role": "user", "content": original_formatted},
        ],
        max_tokens=16000,
    )
    translated = (translate_resp.choices[0].message.content or "").strip()
    if _is_refusal(translated):
        raise RuntimeError(f"diarize-translate refused: {translated[:120]}")
    if not translated:
        raise RuntimeError("diarize-translate returned empty")

    return original_formatted, translated, source_lang


async def _translate_e2e(
    mp3_bytes: bytes,
    openai_client: AsyncOpenAI,
    model: str,
) -> str:
    audio_b64 = base64.b64encode(mp3_bytes).decode()
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": _E2E_PROMPT},
            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "mp3"}},
        ],
    }]
    resp = await openai_client.chat.completions.create(
        model=model,
        modalities=["text"],
        messages=messages,
    )
    text = resp.choices[0].message.content
    if _is_refusal(text):
        raise RuntimeError(f"e2e path refused: {text[:120] if text else ''}")
    if not text:
        raise RuntimeError("e2e path returned empty content")
    return _strip_preamble(text)


async def _translate_fallback(
    mp3_bytes: bytes,
    openai_client: AsyncOpenAI,
    settings: Settings,
) -> tuple[str, str, str]:
    transcription = await openai_client.audio.transcriptions.create(
        model=settings.model_transcription,
        file=("audio.mp3", mp3_bytes),
        response_format="json",
    )
    original_text = (transcription.text or "").strip()
    # gpt-4o-mini-transcribe does not return `language` in json mode; whisper-1 does.
    source_lang = getattr(transcription, "language", None) or "unknown"

    if not original_text:
        raise RuntimeError("fallback: empty transcription")

    if source_lang.lower() in ("en", "english"):
        return original_text, original_text, source_lang

    chunk_size = 15000
    chunks = [original_text[i:i + chunk_size] for i in range(0, len(original_text), chunk_size)]
    translated_chunks: list[str] = []
    for i, chunk in enumerate(chunks):
        logger.info(f"fallback translate chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        resp = await openai_client.chat.completions.create(
            model=settings.model_transcript,
            messages=[{
                "role": "user",
                "content": (
                    "Translate the following transcript to English. Preserve meaning accurately. "
                    "Output only the translation, no preamble.\n\n" + chunk
                ),
            }],
            max_tokens=16000,
        )
        chunk_text = resp.choices[0].message.content or ""
        if _is_refusal(chunk_text):
            logger.warning(f"fallback chunk {i + 1} refused, using original")
            translated_chunks.append(chunk)
        else:
            translated_chunks.append(chunk_text.strip())

    return original_text, "\n".join(translated_chunks), source_lang


_RECOVERABLE_ERRORS = (
    openai_exc.BadRequestError,
    openai_exc.NotFoundError,
    openai_exc.APIError,
    RuntimeError,
)


async def translate_media(
    file_bytes: bytes,
    filename: str,
    openai_client: AsyncOpenAI,
    settings: Settings,
) -> TranslateResult:
    mp3_bytes = await _to_mp3(file_bytes, filename)
    logger.info(f"audio normalized: {len(file_bytes)} bytes ({filename}) -> {len(mp3_bytes)} bytes (mp3)")

    # Primary: diarize-aware pipeline (real speaker labels, same-lang transcription + translation).
    try:
        original_text, translated_text, source_lang = await _translate_diarize(
            mp3_bytes, openai_client, settings
        )
        return TranslateResult(
            translated_text=translated_text,
            path_used="diarize",
            source_lang=source_lang,
            original_text=original_text,
        )
    except _RECOVERABLE_ERRORS as e:
        logger.warning(f"diarize path failed ({type(e).__name__}: {e}); trying e2e audio-preview")

    # Secondary: single-call audio-preview (no speaker labels, but works as last-resort).
    try:
        translated = await _translate_e2e(
            mp3_bytes, openai_client, settings.model_audio_translator
        )
        return TranslateResult(translated_text=translated, path_used="e2e")
    except _RECOVERABLE_ERRORS as e:
        logger.warning(f"e2e path failed ({type(e).__name__}: {e}); falling back to transcribe+translate")

    original_text, translated_text, source_lang = await _translate_fallback(
        mp3_bytes, openai_client, settings
    )
    return TranslateResult(
        translated_text=translated_text,
        path_used="fallback",
        source_lang=source_lang,
        original_text=original_text,
    )


if __name__ == "__main__":
    import asyncio
    import sys

    async def _main():
        audio_path = sys.argv[1] if len(sys.argv) > 1 else "samples/test.mp3"
        with open(audio_path, "rb") as f:
            file_bytes = f.read()
        settings = Settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        result = await translate_media(
            file_bytes,
            filename=audio_path.rsplit("/", 1)[-1],
            openai_client=client,
            settings=settings,
        )
        print(f"path_used:     {result.path_used}")
        print(f"source_lang:   {result.source_lang}")
        print(f"original_text: {result.original_text!r}")
        print("---- translation ----")
        print(result.translated_text)

    asyncio.run(_main())
