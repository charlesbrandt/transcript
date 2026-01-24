FROM python:3.10-slim

WORKDIR /app

# Install system dependencies including audio libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libportaudio2 \
    libasound2-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

# Install uv and dependencies
RUN pip install uv && \
    uv pip install --system -r requirements.txt

# Allow files to be owned by your system user. Adjust as needed
ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID appgroup && useradd -u $UID -g $GID -ms /bin/bash appuser
USER appuser

# Copy application code
COPY . .

# Command will be specified in docker-compose.yml