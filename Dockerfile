FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates ffmpeg fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnss3 libxcomposite1 libxdamage1 libxkbcommon0 libxrandr2 wget xvfb \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps firefox

COPY pyproject.toml README.md ./
COPY src ./src

ENV TELEGRAM_BOT_TOKEN="" \
    BOT_TIMEZONE="Europe/Rome"

CMD ["python", "-m", "deilabs_bot.bot"]
