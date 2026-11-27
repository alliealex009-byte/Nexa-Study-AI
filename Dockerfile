# Lightweight ARM64 / aarch64 compatible image for Oracle Cloud Free Tier (2 OCPU, 12 GB RAM)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install lightweight native ARM64 Tesseract OCR engine (no heavy PyTorch/EasyOCR needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Run as non-root user for security
RUN useradd --create-home --shell /bin/bash nexa \
    && chown -R nexa:nexa /app
USER nexa

CMD ["python", "bot.py"]
