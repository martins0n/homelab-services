FROM python:3.10-slim

# ffmpeg + libsndfile for audio I/O; ffmpeg/yt-dlp also used to fetch audio from a URL
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch from PyTorch's CPU index. torch 2.12 gates its CUDA deps on
# `platform_system == "Linux"` (not architecture), so the default wheel drags
# gigabytes of unusable NVIDIA libraries onto the arm64 Pi. The +cpu wheels skip
# all of that and are much smaller (~143 MB vs ~406 MB for torch alone).
# extra-index-url (not index-url) so torch's own deps (typing-extensions, sympy,
# …) still resolve from PyPI; the explicit +cpu pin only exists on the torch index.
RUN pip install --no-cache-dir \
    torch==2.12.0+cpu torchaudio==2.11.0+cpu \
    --extra-index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# HF weights cache -> mount a volume here so models aren't re-downloaded on restart
ENV HF_HOME=/models

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
