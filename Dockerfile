# Radio Show Recorder Dockerfile
# Multi-stage build for smaller final image

FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Final stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    rclone \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash recorder \
    && mkdir -p /app/recordings /app/data \
    && chown -R recorder:recorder /app

# Copy application code
COPY --chown=recorder:recorder src/ ./src/

# Switch to non-root user
USER recorder

# Set Python path
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check - verify the process is running
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -f "python -m src.main" || exit 1

# Run the application
CMD ["python", "-m", "src.main"]
