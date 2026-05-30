FROM python:3.10-slim

# ffmpeg + libsndfile for audio I/O; ffmpeg/yt-dlp also used to fetch audio from a URL
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# HF weights cache -> mount a volume here so models aren't re-downloaded on restart
ENV HF_HOME=/models

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
