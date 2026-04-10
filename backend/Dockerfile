FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Limit ONNX/RapidOCR thread usage to prevent "Resource temporarily unavailable" errors
# With 4 workers, this keeps total threads well within Railway's limits.
ENV OMP_NUM_THREADS=2
ENV MKL_NUM_THREADS=2
ENV OCR_POOL_SIZE=1

# Pre-install robust NumPy version to prevent 2.x conflicts
RUN pip install "numpy<2.0.0"

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Pre-download OCR models (if applicable)
RUN python preload_models.py

# Install gunicorn for multi-worker support
RUN pip install --no-cache-dir gunicorn

# Run application with gunicorn + uvicorn workers for high concurrency
# Configured for Railway's 8 vCPU, 8GB RAM per replica.
# WEB_WORKERS uses 4 by default (since RapidOCR model is tiny).
CMD sh -c "gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WEB_WORKERS:-4} \
    --bind 0.0.0.0:${PORT:-8000} \
    --timeout 300 \
    --max-requests 500 \
    --max-requests-jitter 50"
