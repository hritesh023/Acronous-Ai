FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY backend_api/requirements.txt /app/requirements-api.txt
COPY requirements-cloud.txt /app/requirements-cloud.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/requirements-cloud.txt

# Copy application code
COPY apex_llm/ /app/apex_llm/
COPY backend_api/ /app/backend_api/
COPY data/ /app/data/

# Create necessary directories
RUN mkdir -p /app/data/models /app/data

# Expose port (Render/Railway will set PORT env var)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)"

# Start the server
CMD ["sh", "-c", "cd /app/backend_api && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
