"""ml-service: small FastAPI wrapper around heavyweight ML models that don't
belong in the main bot image. Exposes speaker diarization; add further
endpoints here as needed.

POST /diarize  (multipart: file=<audio>  OR  url=<media url>)
               optional: proxy=<http proxy>,
                         num_speakers=<int>  (exact count, if known)
                         max_speakers=<int>  (pyannote only; cap)
               -> {"turns": [{start,end,speaker}], "num_speakers": N}
GET  /health   -> readiness + which engine/model is loaded

Two diarization engines, chosen at startup via ENGINE:
  - sherpa   (default): sherpa-onnx — pyannote-3.0 segmentation (ONNX) + a
             speaker-embedding extractor (WeSpeaker CAM++) + fast clustering.
             ~35 MB of ONNX, no PyTorch, ~10x faster than pyannote on the Pi's
             CPU. Speaker count is auto-detected from a cosine threshold
             (SHERPA_CLUSTER_THRESHOLD) unless num_speakers is supplied.
  - pyannote: pyannote.audio + torch — higher accuracy on speaker counting /
             boundaries, but runs slower than real-time on the arm64 CPU.

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

ENGINE = os.environ.get("ENGINE", "sherpa").lower()

# --- pyannote (optional engine) ---
PYANNOTE_MODEL = os.environ.get("PYANNOTE_MODEL", "pyannote/speaker-diarization-community-1")
HF_TOKEN = os.environ.get("HF_TOKEN")

# --- sherpa-onnx (default engine) ---
SHERPA_SEG_MODEL = os.environ.get(
    "SHERPA_SEGMENTATION_MODEL",
    "/app/models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx",
)
# Multilingual CAM++ (3D-Speaker, CN-Celeb + VoxCeleb). The English-only
# wespeaker model scattered on non-English speech — a 22-min Armenian clip
# auto-detected as 16 speakers. This model holds a 4-speaker reference clip at
# exactly 4 while cutting the Armenian over-split, at the same speed (RTF ~0.26).
SHERPA_EMB_MODEL = os.environ.get(
    "SHERPA_EMBEDDING_MODEL",
    "/app/models/3dspeaker_campplus_sv_zh_en.onnx",
)
# Cosine-distance threshold for auto speaker-count detection: smaller -> more
# speakers, larger -> fewer. 0.7 (was 0.5) — 0.5 over-split long conversations;
# 0.7 is the best auto setting that still holds a 4-speaker reference clip at 4.
# Auto-counting is inherently approximate on long multilingual audio; pass
# num_speakers to force an exact count (threshold then ignored).
SHERPA_THRESHOLD = float(os.environ.get("SHERPA_CLUSTER_THRESHOLD", "0.7"))
SHERPA_NUM_THREADS = int(os.environ.get("SHERPA_NUM_THREADS", "4"))

TARGET_SR = 16000

# Loaded at startup; exactly one of these is populated depending on ENGINE.
_pipeline = None      # pyannote Pipeline
_sd = None            # sherpa OfflineSpeakerDiarization (auto-count default)

# Serialize the heavy CPU work: two concurrent multi-threaded diarizations would
# oversubscribe the 8 cores and run slower than one-at-a-time.
_diar_lock = asyncio.Lock()


def _build_sherpa(num_clusters: int = -1, threshold: float = SHERPA_THRESHOLD):
    """Construct an OfflineSpeakerDiarization. num_clusters=-1 -> auto-detect via
    threshold; a positive value forces an exact speaker count (threshold ignored)."""
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=SHERPA_SEG_MODEL
            ),
            num_threads=SHERPA_NUM_THREADS,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=SHERPA_EMB_MODEL,
            num_threads=SHERPA_NUM_THREADS,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_clusters, threshold=threshold
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError(
            f"invalid sherpa config (check model paths: seg={SHERPA_SEG_MODEL}, "
            f"emb={SHERPA_EMB_MODEL})"
        )
    return sherpa_onnx.OfflineSpeakerDiarization(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the selected diarization engine once at startup."""
    global _pipeline, _sd
    if ENGINE == "pyannote":
        from pyannote.audio import Pipeline

        logger.info("loading pyannote pipeline: %s", PYANNOTE_MODEL)
        _pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, token=HF_TOKEN)
        logger.info("pyannote pipeline loaded")
    else:
        logger.info(
            "loading sherpa-onnx diarization (seg=%s, emb=%s, threshold=%.2f, threads=%d)",
            SHERPA_SEG_MODEL, SHERPA_EMB_MODEL, SHERPA_THRESHOLD, SHERPA_NUM_THREADS,
        )
        _sd = _build_sherpa()
        logger.info("sherpa-onnx loaded (sample_rate=%d)", _sd.sample_rate)
    yield
    _pipeline = None
    _sd = None


app = FastAPI(title="ml-service", lifespan=lifespan)


@app.get("/health")
def health():
    loaded = _pipeline is not None or _sd is not None
    model = PYANNOTE_MODEL if ENGINE == "pyannote" else f"sherpa:{os.path.basename(SHERPA_EMB_MODEL)}"
    return {"status": "ok", "engine": ENGINE, "model": model, "loaded": loaded}


async def _run(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {err.decode('utf-8', 'replace')[-400:]}")
    return out


async def _to_wav16k(src_path: str, dest_dir: str) -> str:
    """ffmpeg-transcode any input to 16 kHz mono pcm_s16le wav. Returns wav path."""
    wav_path = os.path.join(dest_dir, "audio16k.wav")
    await _run("ffmpeg", "-y", "-i", src_path, "-vn", "-ac", "1", "-ar", str(TARGET_SR),
               "-c:a", "pcm_s16le", wav_path)
    return wav_path


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
    return await _to_wav16k(raw_path, dest_dir)


def _read_wav_16k_mono(path: str):
    """Load `path` as a float32 mono numpy array at 16 kHz. Reads with soundfile;
    if the rate/layout is wrong it transcodes via ffmpeg first (the url and bot
    paths already deliver 16 kHz mono, so this is a defensive fallback)."""
    import numpy as np
    import soundfile as sf

    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    audio = audio[:, 0]  # take first channel -> mono
    if sr != TARGET_SR:
        import subprocess

        out = path + ".16k.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "1",
             "-ar", str(TARGET_SR), "-c:a", "pcm_s16le", out],
            check=True,
        )
        audio, sr = sf.read(out, dtype="float32", always_2d=True)
        audio = audio[:, 0]
    return np.ascontiguousarray(audio), sr


def _diarize_sherpa(path: str, num_speakers: int | None) -> list[dict]:
    audio, _ = _read_wav_16k_mono(path)
    sd = _sd if not num_speakers else _build_sherpa(num_clusters=num_speakers)
    result = sd.process(audio).sort_by_start_time()
    return [
        {"start": round(seg.start, 3), "end": round(seg.end, 3),
         "speaker": f"SPEAKER_{seg.speaker:02d}"}
        for seg in result
    ]


def _diarize_pyannote(path: str, num_speakers: int | None, max_speakers: int | None) -> list[dict]:
    kwargs = {}
    if num_speakers:
        kwargs["num_speakers"] = num_speakers
    elif max_speakers:
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


def _diarize_file(path: str, num_speakers: int | None, max_speakers: int | None) -> list[dict]:
    if ENGINE == "pyannote":
        return _diarize_pyannote(path, num_speakers, max_speakers)
    return _diarize_sherpa(path, num_speakers)


@app.post("/diarize")
async def diarize(
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    proxy: str | None = Form(default=None),
    num_speakers: int | None = Form(default=None),
    max_speakers: int | None = Form(default=None),
):
    if _pipeline is None and _sd is None:
        raise HTTPException(status_code=503, detail="engine not loaded yet")
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
            async with _diar_lock:
                turns = await run_in_threadpool(_diarize_file, path, num_speakers, max_speakers)
        except Exception as e:
            logger.exception("diarization failed")
            raise HTTPException(status_code=500, detail=f"diarization failed: {e}")

    return {"turns": turns, "num_speakers": len({t["speaker"] for t in turns})}


if __name__ == "__main__":
    # Live sanity check: `python app.py <audio.wav> [num_speakers]` loads the
    # configured engine and prints the diarization turns. Lets you eyeball the
    # speaker split / threshold without standing up the HTTP server.
    import json
    import sys

    wav = sys.argv[1] if len(sys.argv) > 1 else "audio.wav"
    ns = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if ENGINE == "pyannote":
        from pyannote.audio import Pipeline

        _pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, token=HF_TOKEN)
    else:
        _sd = _build_sherpa(num_clusters=ns if ns else -1)
    turns = _diarize_file(wav, ns, None)
    print(json.dumps({
        "engine": ENGINE,
        "num_speakers": len({t["speaker"] for t in turns}),
        "n_turns": len(turns),
        "turns": turns,
    }, ensure_ascii=False, indent=2))
