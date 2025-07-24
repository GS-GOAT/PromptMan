# 1. Build code2prompt using Rust image
FROM rust:1.81 AS builder

RUN cargo install code2prompt --locked --version 3.0.2

# 2. Setup Python runtime environment
FROM python:3.10-slim

WORKDIR /app

# environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000
ENV REDIS_HOST redis
ENV REDIS_PORT 6379
ENV ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
# Playwright needs this env var
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# Playwright browser dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Copy the compiled code2prompt binary from the builder stage(Multi-Stage Builder)
COPY --from=builder /usr/local/cargo/bin/code2prompt /usr/local/bin/code2prompt

RUN code2prompt --version

# Create non-root user WITH a home directory and explicit shell setting
RUN addgroup --system app && \
    adduser --system --group app --home /home/app --shell /bin/false

# Python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Run crawl4ai/playwright setup
RUN mkdir -p ${PLAYWRIGHT_BROWSERS_PATH}
RUN python -m playwright install --with-deps chromium
RUN crawl4ai-setup

# backend application code
COPY . /app

# Create runtime/cache directories BEFORE final chown
RUN mkdir -p /app/temp /app/results /app/temp_clones /app/.cache

RUN chown -R app:app /app /home/app

ENV HOME=/home/app

# Change to non-root user
USER app

EXPOSE $PORT

# Runs the application
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "--bind", "0.0.0.0:8000", "main:app"]