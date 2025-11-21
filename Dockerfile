# Dockerfile - slim, installs Playwright runtime deps and Python libs
FROM python:3.10-slim

# Install system deps needed for Playwright + ffmpeg (for some audio)
RUN apt-get update && apt-get install -y \
    wget ca-certificates git gnupg ffmpeg \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libasound2 libxshmfence1 libpangocairo-1.0-0 libpango-1.0-0 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (use the official playwright CLI)
RUN pip install playwright && playwright install chromium

# Copy app
COPY main.py .

ENV PORT=80
EXPOSE 80

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
