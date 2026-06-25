FROM python:3.11-slim

# Install ffmpeg and clean up apt caches to keep the image lightweight
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create a temporary directory for video downloads
RUN mkdir -p temp && chmod 777 temp

# Run the bot
CMD ["python", "main.py"]
