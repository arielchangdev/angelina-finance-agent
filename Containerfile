# Angelina Finance Agent - Podman Container
# Base image: Python 3.12 slim for smaller footprint
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy and install Python dependencies
COPY requirements-angelina.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/

# Copy static assets
COPY static/ static/

# Copy production environment file
COPY deploy/.env.production .env

# Copy configuration (service-account.json, etc.)
COPY config/ config/

# Create data directories
RUN mkdir -p data/vector_store data/notebooklm

# Expose application port
EXPOSE 8080

# Volume mount points for persistent data and credentials
VOLUME ["/app/data", "/app/config"]

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD ["python", "-c", "import httpx; r = httpx.get('http://localhost:8080/health'); assert r.status_code == 200"]

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]