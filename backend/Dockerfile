# Stage 1: Build code2prompt using Rust image
FROM rust:1.81 AS builder

# Install code2prompt using cargo
RUN cargo install code2prompt --locked --version 3.0.2

# Stage 2: Setup Python runtime environment
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000
ENV REDIS_HOST redis
ENV REDIS_PORT 6379
ENV ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"

# Install git
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Copy the compiled code2prompt binary from the builder stage
COPY --from=builder /usr/local/cargo/bin/code2prompt /usr/local/bin/code2prompt

# Verify code2prompt is copied and executable
RUN code2prompt --version

# Create non-root user
RUN addgroup --system app && adduser --system --group app
RUN chown -R app:app /app

# Install Python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY . /app

# Create directories and set permissions
RUN mkdir -p /app/temp /app/results /app/temp_clones && \
    chown -R app:app /app/temp /app/results /app/temp_clones

# Change to non-root user
USER app

# Expose the port the app runs on
EXPOSE $PORT

# Run the application using Gunicorn with Uvicorn workers
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "--bind", "0.0.0.0:8000", "main:app"]