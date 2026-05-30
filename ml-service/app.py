"""ml-service: small FastAPI wrapper around heavyweight ML models that don't
belong in the main bot image. Currently exposes speaker diarization (pyannote);
add further endpoints here as needed.

POST /diarize  (multipart: file=<audio>  OR  url=<media url>)
               optional: proxy=<http proxy>, max_speakers=<int>
               -> {"turns": [{start,end,speaker}], "num_speakers": N}
GET  /health   -> readiness + which model is loaded

When given a `url`, the service downloads the audio itself (yt-dlp) and transcodes
to 16 kHz mono wav (ffmpeg), so the caller never has to handle the audio.
"""
import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml-service")

MODEL = os.environ.get("PYANNOTE_MODEL", "pyannote/speaker-diarization-community-1")
HF_TOKEN = os.environ.get("HF_TOKEN")

_pipeline = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the diarization pipeline once at startup (downloads weights on first
    run into HF_HOME, which should be a mounted volume to avoid re-downloading)."""
    global _pipeline
    from pyannote.audio import Pipeline

    logger.info("loading pyannote pipeline: %s", MODEL)
    _pipeline = Pipeline.from_pretrained(MODEL, token=HF_TOKEN)
    logger.info("pipeline loaded")
    yield
    _pipeline = None


app = FastAPI(title="ml-service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL, "loaded": _pipeline is not None}


async def _run(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {err.decode('utf-8', 'replace')[-400:]}")
    return out


async def _download_to_wav(url: str, proxy: str | None, dest_dir: str) -> str:
    """yt-dlp bestaudio -> ffmpeg 16 kHz mono wav. Returns the wav path."""
    raw_tmpl = os.path.join(dest_dir, "audio.%(ext)s")
    dl = ["yt-dlp", "-q", "--no-warnings", "-f", "bestaudio", "-o", raw_tmpl]
    if proxy:
        dl += ["--proxy", proxy]
    dl.append(url)
    await _run(*dl)
    files = [f for f in os.listdir(dest_dir) if f.startswith("audio.")]
    if not files:
        raise RuntimeError("yt-dlp produced no output")
    raw_path = os.path.join(dest_dir, files[0])
    wav_path = os.path.join(dest_dir, "audio16k.wav")
    await _run("ffmpeg", "-y", "-i", raw_path, "-vn", "-ac", "1", "-ar", "16000",
               "-c:a", "pcm_s16le", wav_path)
    return wav_path


def _diarize_file(path: str, max_speakers: int | None) -> list[dict]:
    kwargs = {}
    if max_speakers:
        kwargs["max_speakers"] = max_speakers
    out = _pipeline(path, **kwargs)
    # Newer pyannote returns DiarizeOutput; prefer the exclusive (non-overlapping)
    # diarization for clean word/cue alignment. Fall back to old Annotation API.
    ann = (
        getattr(out, "exclusive_speaker_diarization", None)
        or getattr(out, "speaker_diarization", None)
        or out
    )
    return [
        {"start": round(turn.start, 3), "end": round(turn.end, 3), "speaker": spk}
        for turn, _, spk in ann.itertracks(yield_label=True)
    ]


@app.post("/diarize")
async def diarize(
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    proxy: str | None = Form(default=None),
    max_speakers: int | None = Form(default=None),
):
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="pipeline not loaded yet")
    if not file and not url:
        raise HTTPException(status_code=400, detail="provide either 'file' or 'url'")

    with tempfile.TemporaryDirectory() as d:
        if url:
            try:
                path = await _download_to_wav(url, proxy, d)
            except Exception as e:
                logger.exception("download failed")
                raise HTTPException(status_code=502, detail=f"download failed: {e}")
        else:
            data = await file.read()
            if not data:
                raise HTTPException(status_code=400, detail="empty audio upload")
            path = os.path.join(d, file.filename or "audio.wav")
            with open(path, "wb") as fh:
                fh.write(data)

        try:
            turns = await run_in_threadpool(_diarize_file, path, max_speakers)
        except Exception as e:
            logger.exception("diarization failed")
            raise HTTPException(status_code=500, detail=f"diarization failed: {e}")

    return {"turns": turns, "num_speakers": len({t["speaker"] for t in turns})}
