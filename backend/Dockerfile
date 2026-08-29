FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# One OS thread per OCR engine. ONNX Runtime otherwise grabs every core per
# engine, so engines contend instead of scaling — measured 1.06 img/s whether
# 1, 4 or 8 workers were running. Parallelism now comes from OCR_POOL_SIZE.
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV OCR_THREADS_PER_ENGINE=1
# 0 = auto-size the engine pool from the container's CPU count at startup.
ENV OCR_POOL_SIZE=0

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

# ONE worker process, on purpose. Upload sessions live in an in-process dict
# (core/security.py temp_dirs); with >1 worker a chunked upload's later chunks
# land on a different process, silently start a new session, and the earlier
# chunks become unreachable. Throughput comes from the in-process OCR engine
# pool instead, which benchmarks faster anyway (2.21 img/s at pool=10 vs
# 1.78 img/s across 5 processes on a 10-core host).
# --max-requests is omitted deliberately: recycling a worker would destroy
# every live session's temp directory mid-run.
CMD sh -c "gunicorn main:app \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers ${WEB_WORKERS:-1} \
    --bind 0.0.0.0:${PORT:-8000} \
    --timeout 1800"
