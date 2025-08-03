FROM python:3.11-slim

# Install system dependencies including FFmpeg and SMB tools
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    cifs-utils \
    samba-client \
    && rm -rf /var/lib/apt/lists/*

# Verify FFmpeg installation
RUN ffmpeg -version

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs /mnt/nas

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Worker service port
EXPOSE 8000

# Create non-root user for security (but allow sudo for mounting)
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app \
    && chown -R app:app /mnt/nas

# Switch to app user
USER app

# Run the FastAPI worker application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]