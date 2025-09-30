# Railway-ready image with Python + Chromium + chromedriver
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install Chromium & chromedriver and deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver fonts-liberation \
    ca-certificates curl wget unzip gnupg \
    && rm -rf /var/lib/apt/lists/*

# Set Chromium paths for Selenium (if needed)
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROME_PATH=/usr/bin/chromium

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py /app/

# Railway uses PORT env for web; our bot is a worker, so no exposure needed.
# Just run the bot.
CMD ["python","bot.py"]
