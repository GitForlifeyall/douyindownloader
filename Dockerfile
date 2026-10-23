# ==============================================================================
# Douyin / TikTok Headless AI Dubbing Studio - Dockerfile for Google Cloud Run (GPU)
# ==============================================================================

FROM python:3.11-bookworm

# Prevent interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies: FFmpeg, Git, OpenGL, GLib, OpenMP
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Step 1: Install PyTorch with CUDA 12.1 acceleration (cached layer)
RUN pip install --no-cache-dir \
    torch==2.3.1 torchvision==0.18.1 torchaudio==2.3.1 \
    --index-url https://download.pytorch.org/whl/cu121

# Step 2: Install application requirements
COPY requirements.docker.txt /app/requirements.docker.txt
RUN pip install --no-cache-dir -r requirements.docker.txt

# Step 3: Copy project source directories & models
COPY dubbing_studio /app/dubbing_studio
COPY TikTokDownloader /app/TikTokDownloader
COPY video-subtitle-remover-main /app/video-subtitle-remover-main
COPY remove_subtitles.py /app/remove_subtitles.py
COPY pipeline.py /app/pipeline.py
COPY server.py /app/server.py

# Create output directory for intermediate renders
RUN mkdir -p /app/output

# Google Cloud Run environment settings
ENV PORT=8080
ENV HARDWARD_ACCELERATION_OPTION=True
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

EXPOSE 8080

# Run FastAPI server (listens on PORT for Google Cloud Run)
CMD ["python", "server.py"]
