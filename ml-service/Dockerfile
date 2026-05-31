FROM python:3.10-slim

# ffmpeg + libsndfile for audio I/O; ffmpeg/yt-dlp also used to fetch audio from a
# URL; curl downloads the sherpa-onnx diarization models at build time; bzip2 is
# what `tar xjf` shells out to for the .tar.bz2 model archive (the slim base image
# ships tar but NOT the bzip2 binary, so extraction fails without it).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 curl ca-certificates bzip2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch from PyTorch's CPU index. Only needed for the optional pyannote
# engine (ENGINE=pyannote); the default sherpa-onnx engine has no torch dependency.
# torch 2.12 gates its CUDA deps on `platform_system == "Linux"` (not architecture),
# so the default wheel drags gigabytes of unusable NVIDIA libraries onto the arm64
# Pi. The +cpu wheels skip all of that and are much smaller (~143 MB vs ~406 MB for
# torch alone). extra-index-url (not index-url) so torch's own deps (typing-extensions,
# sympy, …) still resolve from PyPI; the explicit +cpu pins only exist on the torch
# index. torchcodec (pyannote's audio decoder) MUST also be the +cpu build — its
# default wheel links CUDA (libnvrtc.so.13) and fails to load without a GPU.
RUN pip install --no-cache-dir \
    torch==2.12.0+cpu torchaudio==2.11.0+cpu torchcodec==0.13.0+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the sherpa-onnx diarization models so the default engine starts
# offline and the image is self-contained. These live OUTSIDE the /models volume
# (which holds the pyannote HF cache) so the named-volume mount can't shadow them.
# Segmentation = pyannote-3.0 (ONNX). Two embedders: multilingual CAM++ (default,
# 3D-Speaker zh_en — robust on non-English) and the older English-only WeSpeaker
# CAM++ (kept for SHERPA_EMBEDDING_MODEL overrides / comparison).
ARG SHERPA_REL=https://github.com/k2-fsa/sherpa-onnx/releases/download
RUN mkdir -p /app/models && cd /app/models \
    && curl -fsSL -o seg.tar.bz2 \
        "${SHERPA_REL}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2" \
    && tar xjf seg.tar.bz2 && rm seg.tar.bz2 \
    && curl -fsSL -o "wespeaker_en_voxceleb_CAM++.onnx" \
        "${SHERPA_REL}/speaker-recongition-models/wespeaker_en_voxceleb_CAM%2B%2B.onnx" \
    && curl -fsSL -o "3dspeaker_campplus_sv_zh_en.onnx" \
        "${SHERPA_REL}/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"

# Pre-download Piper TTS voices (sherpa-onnx VITS) so the bot can read translated
# transcripts aloud (Android Chrome's Read Aloud is broken on Telegraph pages).
# en_US "low" voices, ~20 MB each; one per speaker, round-robined by the bot.
ARG PIPER_REL=https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models
RUN set -eux; mkdir -p /app/models/tts; cd /app/models/tts; \
    for v in amy ryan kathleen lessac; do \
        curl -fsSL -o "$v.tar.bz2" "${PIPER_REL}/vits-piper-en_US-$v-low.tar.bz2"; \
        tar xjf "$v.tar.bz2"; \
        rm "$v.tar.bz2"; \
    done

COPY app.py .

# Default engine: sherpa-onnx (lightweight, CPU, ~10x faster than pyannote here).
# Set ENGINE=pyannote to use the higher-accuracy torch pipeline instead.
ENV ENGINE=sherpa
# Multilingual CAM++ embedder + threshold 0.7 are the prod-effective defaults.
# The deploy webhook only `--pull always`s the image (it never git-pulls the
# compose file), so these image ENVs — not the compose env — are what flip the
# defaults in production.
ENV SHERPA_EMBEDDING_MODEL=/app/models/3dspeaker_campplus_sv_zh_en.onnx
ENV SHERPA_CLUSTER_THRESHOLD=0.7
# Piper TTS: voices baked at /app/models/tts; all speakers read at 0.8x speed
# (slower = easier to follow a translated conversation; user preference).
ENV TTS_MODELS_DIR=/app/models/tts
ENV TTS_SPEED=0.8
# HF weights cache (pyannote engine) -> mount a volume here so models aren't
# re-downloaded on restart.
ENV HF_HOME=/models

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
