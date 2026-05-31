"""Speaker-diarized YouTube transcripts.

Pipeline:
  1. download audio (yt-dlp) and transcode (ffmpeg)
  2. get timed cues:
       - primary: YouTube auto-captions in the original language (free, accurate)
       - fallback: Groq Whisper ASR when the video has no captions
  3. diarization turns from the separate ml-service (pyannote)
  4. align each cue to the max-overlap speaker -> "Speaker N: ..." lines
  5. translate to English preserving the speaker labels
  6. publish to Telegraph

Diarization itself is acoustic, so we always need the audio; only transcription
is skipped when captions exist (the cheap, higher-quality path).
"""
import asyncio
import os
import re
import tempfile

import httpx
from loguru import logger
from openai import AsyncOpenAI
from youtube_transcript_api import NoTranscriptFound, YouTubeTranscriptApi

from settings import Settings
from tts_client import voice_for_speaker
from video_translator import _DIARIZE_TRANSLATE_PROMPT, _is_refusal
from youtube import get_youtube_id
from youtube_transcript import _create_telegraph_pages, _summarize


async def _ffmpeg(in_bytes: bytes, in_ext: str, out_args: list[str]) -> bytes:
    """Run ffmpeg on in-memory audio, returning the transcoded bytes via pipe."""
    with tempfile.NamedTemporaryFile(suffix=f".{in_ext}", delete=False) as inf:
        inf.write(in_bytes)
        in_path = inf.name
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", in_path, *out_args, "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0 or not out:
            raise RuntimeError(f"ffmpeg failed: {err.decode('utf-8', 'replace')[-400:]}")
        return out
    finally:
        try:
            os.unlink(in_path)
        except OSError:
            pass


async def _to_wav16k(in_bytes: bytes, in_ext: str) -> bytes:
    return await _ffmpeg(in_bytes, in_ext, ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav"])


async def _to_mp3_small(in_bytes: bytes, in_ext: str) -> bytes:
    return await _ffmpeg(in_bytes, in_ext, ["-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-c:a", "libmp3lame", "-f", "mp3"])


async def _download_audio(url: str, proxy: str | None) -> tuple[bytes, str]:
    """Download bestaudio via yt-dlp into a temp dir; return (bytes, ext)."""
    with tempfile.TemporaryDirectory() as d:
        out_tmpl = os.path.join(d, "audio.%(ext)s")
        args = ["yt-dlp", "-q", "--no-warnings", "-f", "bestaudio", "-o", out_tmpl]
        if proxy:
            args += ["--proxy", proxy]
        args.append(url)
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp failed: {err.decode('utf-8', 'replace')[-400:]}")
        files = os.listdir(d)
        if not files:
            raise RuntimeError("yt-dlp produced no output")
        path = os.path.join(d, files[0])
        with open(path, "rb") as f:
            return f.read(), files[0].rsplit(".", 1)[-1].lower()


def _youtube_cues(video_id: str, proxies: dict | None) -> tuple[list[dict], str] | None:
    """Original-language YouTube captions as [{text,start,end}] + language code.
    Prefers a human transcript, else the original auto-generated one."""
    try:
        tl = YouTubeTranscriptApi.list_transcripts(video_id, proxies=proxies)
    except Exception as e:
        logger.info(f"no transcript list for {video_id}: {e}")
        return None

    chosen = next((t for t in tl if not t.is_generated), None) or next(iter(tl), None)
    if chosen is None:
        return None
    data = chosen.fetch()

    def attr(item, name):
        return item[name] if isinstance(item, dict) else getattr(item, name)

    cues = []
    for item in data:
        text = (attr(item, "text") or "").strip()
        if not text:
            continue
        start = float(attr(item, "start"))
        cues.append({"text": text, "start": start, "end": start + float(attr(item, "duration"))})
    return (cues, chosen.language_code) if cues else None


async def _groq_word_cues(mp3_bytes: bytes, settings: Settings) -> tuple[list[dict], str]:
    """Fallback ASR: Groq Whisper with word timestamps -> [{text,start,end}], lang."""
    client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=settings.groq_base_url)
    resp = await client.audio.transcriptions.create(
        model=settings.model_groq_whisper,
        file=("audio.mp3", mp3_bytes),
        response_format="verbose_json",
        timestamp_granularities=["word"],
    )
    d = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
    cues = [
        {"text": w["word"], "start": float(w["start"]), "end": float(w["end"])}
        for w in (d.get("words") or [])
    ]
    return cues, d.get("language") or "unknown"


def _parse_turns(data: dict) -> list[tuple[float, float, str]]:
    return [(float(t["start"]), float(t["end"]), t["speaker"]) for t in data.get("turns", [])]


def _scaled_timeout(duration_sec: float, settings: Settings) -> "httpx.Timeout":
    """Read timeout scaled to audio length (pyannote on CPU runs ~real-time or
    slower); connect stays short so an unreachable ml-service fails fast."""
    read = max(
        float(settings.diarize_timeout),
        settings.diarize_timeout_base + duration_sec * settings.diarize_realtime_factor,
    )
    logger.info(f"diarize: ml-service read timeout = {read:.0f}s for ~{duration_sec/60:.0f} min audio")
    return httpx.Timeout(read, connect=15.0)


async def _diarize_url(
    video_url: str, proxy: str | None, settings: Settings, duration_sec: float, num_speakers: int = -1
) -> list[tuple[float, float, str]]:
    """ml-service downloads the audio itself and returns speaker turns (captions path)."""
    endpoint = settings.ml_service_url.rstrip("/") + "/diarize"
    form = {"url": video_url}
    if proxy:
        form["proxy"] = proxy
    if num_speakers and num_speakers > 0:
        form["num_speakers"] = str(num_speakers)
    async with httpx.AsyncClient(timeout=_scaled_timeout(duration_sec, settings)) as client:
        r = await client.post(endpoint, data=form)
        r.raise_for_status()
        return _parse_turns(r.json())


async def _diarize_file(
    wav_bytes: bytes, settings: Settings, duration_sec: float, num_speakers: int = -1
) -> list[tuple[float, float, str]]:
    """Diarize already-downloaded audio (Groq-fallback path, reuses the download)."""
    endpoint = settings.ml_service_url.rstrip("/") + "/diarize"
    data = {"num_speakers": str(num_speakers)} if num_speakers and num_speakers > 0 else None
    async with httpx.AsyncClient(timeout=_scaled_timeout(duration_sec, settings)) as client:
        r = await client.post(endpoint, files={"file": ("audio.wav", wav_bytes, "audio/wav")}, data=data)
        r.raise_for_status()
        return _parse_turns(r.json())


def align_cues_to_speakers(cues: list[dict], turns: list[tuple[float, float, str]]) -> str:
    """Assign each timed cue to the max-overlap speaker turn (nearest turn if no
    overlap, never a new speaker), merge consecutive, normalize to 'Speaker N:'."""
    def speaker_at(s: float, e: float) -> str:
        best, best_ov = None, 0.0
        for ts, te, lbl in turns:
            ov = max(0.0, min(te, e) - max(ts, s))
            if ov > best_ov:
                best_ov, best = ov, lbl
        if best is not None:
            return best
        mid = (s + e) / 2
        return min(turns, key=lambda t: min(abs(t[0] - mid), abs(t[1] - mid)))[2] if turns else "SPEAKER_00"

    merged: list[list] = []
    for c in cues:
        text = (c["text"] or "").strip()
        if not text:
            continue
        spk = speaker_at(c["start"], c["end"])
        if merged and merged[-1][0] == spk:
            merged[-1][1] += " " + text
        else:
            merged.append([spk, text])

    label_map: dict[str, str] = {}
    lines = []
    for spk, text in merged:
        if spk not in label_map:
            label_map[spk] = f"Speaker {len(label_map) + 1}"
        lines.append(f"{label_map[spk]}: {text}")
    return "\n".join(lines)


async def _translate_preserving_labels(text: str, settings: Settings) -> str:
    """Translate a diarized transcript to English, chunked on speaker-line
    boundaries, keeping every 'Speaker N:' label intact."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    lines = text.split("\n")
    chunks, cur = [], ""
    for ln in lines:
        if cur and len(cur) + len(ln) + 1 > 12000:
            chunks.append(cur)
            cur = ln
        else:
            cur = f"{cur}\n{ln}" if cur else ln
    if cur:
        chunks.append(cur)

    out = []
    for i, chunk in enumerate(chunks):
        logger.info(f"diarize-translate chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        resp = await client.chat.completions.create(
            model=settings.model_transcript,
            messages=[
                {"role": "system", "content": _DIARIZE_TRANSLATE_PROMPT},
                {"role": "user", "content": chunk},
            ],
            max_tokens=16000,
        )
        t = (resp.choices[0].message.content or "").strip()
        out.append(chunk if _is_refusal(t) or not t else t)
    return "\n".join(out)


_SPEAKER_LINE_RE = re.compile(r"^\s*Speaker\s+(\d+)\s*:\s*(.*)$")


def _diar_tts_segments(diarized_text: str) -> list[dict]:
    """Turn 'Speaker N: ...' lines into [{voice, text}] for per-speaker TTS.
    Each speaker number maps to a distinct pool voice (round-robin); a line with
    no speaker label is appended to the previous segment so wrapped text stays
    with its speaker."""
    segments: list[dict] = []
    for line in diarized_text.split("\n"):
        m = _SPEAKER_LINE_RE.match(line)
        if m:
            text = m.group(2).strip()
            if text:
                segments.append({"voice": voice_for_speaker(int(m.group(1))), "text": text})
        else:
            extra = line.strip()
            if extra and segments:
                segments[-1]["text"] += " " + extra
    return segments


async def process_youtube_diarize(url: str, num_speakers: int = -1) -> dict:
    """Full diarized-transcript pipeline. Returns a dict with transcript_urls,
    original_language, num_speakers, and source ('captions' | 'asr').

    num_speakers > 0 forces an exact speaker count (passed to ml-service); -1
    lets the engine auto-detect. Auto-detection over-splits on long multilingual
    audio, so the exact-count hint is the reliable path for known counts."""
    settings = Settings()
    video_id = get_youtube_id(url)
    if not video_id:
        raise ValueError("could not parse YouTube id")
    logger.info(f"diarize: processing {video_id} (num_speakers={num_speakers})")

    proxy = settings.youtube_proxy_url
    proxies = {"https": proxy} if proxy else None

    # Captions first (free, no audio). If present, ml-service downloads the audio
    # itself for diarization so the bot never handles it. Only the no-caption
    # fallback downloads audio here (reused for both Groq ASR and diarization).
    cues_lang = await asyncio.to_thread(_youtube_cues, video_id, proxies)
    if cues_lang:
        cues, lang = cues_lang
        source = "captions"
        duration = max((c["end"] for c in cues), default=0.0)  # last cue end ≈ video length
        logger.info(
            f"diarize: using {len(cues)} caption cues ({lang}, ~{duration/60:.0f} min); ml-service will fetch audio"
        )
        turns = await _diarize_url(url, proxy, settings, duration, num_speakers)
    else:
        logger.info("diarize: no captions, falling back to Groq ASR")
        raw_audio, ext = await _download_audio(url, proxy)
        wav = await _to_wav16k(raw_audio, ext)
        mp3 = await _to_mp3_small(raw_audio, ext)
        duration = len(wav) / 32000.0  # 16 kHz mono s16le → 32000 bytes/sec
        turns_task = asyncio.create_task(_diarize_file(wav, settings, duration, num_speakers))
        cues, lang = await _groq_word_cues(mp3, settings)
        source = "asr"
        logger.info(f"diarize: Groq produced {len(cues)} word cues ({lang})")
        turns = await turns_task

    num_speakers = len({t[2] for t in turns})
    logger.info(f"diarize: {len(turns)} turns, {num_speakers} speakers")

    diarized = align_cues_to_speakers(cues, turns)
    if not diarized:
        raise RuntimeError("diarize: empty aligned transcript")

    is_english = lang.lower().startswith("en")
    translated = diarized if is_english else await _translate_preserving_labels(diarized, settings)

    # Read-aloud audio (per-speaker voices) only when we actually translated to
    # English. For English or Russian sources the user listens to the original, so
    # skip synthesis. The handler turns these segments into a Telegram audio message.
    tts_segments = None
    if not (lang.lower().startswith("en") or lang.lower().startswith("ru")):
        tts_segments = _diar_tts_segments(translated)

    header = f"SPEAKER-DIARIZED TRANSCRIPT ({num_speakers} speakers, source: {source})\n\n"
    transcript_urls = await _create_telegraph_pages(
        f"Diarized Transcript: {video_id}", header + translated
    )

    # Summarize the speaker-labeled transcript (same summarizer as the plain
    # transcript path); the Speaker N: labels stay in the input so the summary
    # can attribute points to speakers. Mirrors process_youtube_transcript's
    # summary_text / summary_url so the diarized reply isn't missing a summary.
    summary_text = await _summarize(translated, settings)
    summary_urls = await _create_telegraph_pages(f"Diarized Summary: {video_id}", summary_text)

    return {
        "video_id": video_id,
        "original_language": lang,
        "num_speakers": num_speakers,
        "source": source,
        "transcript_urls": transcript_urls,
        "summary_url": summary_urls[0] if summary_urls else None,
        "summary_text": summary_text,
        "tts_segments": tts_segments,
    }


if __name__ == "__main__":
    import sys

    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=0GqGWC3tjPI"
        n = int(sys.argv[2]) if len(sys.argv) > 2 else -1
        result = await process_youtube_diarize(url, num_speakers=n)
        print(result)

    asyncio.run(_main())
