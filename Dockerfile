FROM python:3.11-slim

# Install ffmpeg and nodejs (for yt-dlp YouTube JS extraction) and clean up apt caches
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Run unit tests at build time so deployments fail fast if any test breaks
RUN python -m compileall -q main.py handlers services tests \
    && python -m unittest discover -s tests -v \
    && rm -rf temp

# Create a temporary directory for video downloads
RUN mkdir -p temp && chmod 777 temp

# Run the bot
CMD ["python", "main.py"]
