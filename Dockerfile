# Use Python 3.13 slim image for smaller size
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies.
# fonts-dejavu-core is required by Pillow to draw the donation progress bar;
# the slim image ships no fonts at all and the bar falls back to an unreadable
# bitmap face without it. curl is used by the healthcheck below.
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash riko && \
    chown -R riko:riko /app
USER riko

# Web server (leaderboards, donations page, Ko-fi webhook)
EXPOSE 3000

# Health check. The old version listed processes and discarded the result, so
# it passed even when the bot had crashed. This one asks the web server.
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${WEB_PORT:-3000}/healthz || exit 1

# Run the bot
CMD ["python", "bot.py"] 