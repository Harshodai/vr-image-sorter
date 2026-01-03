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

# Argument to control GPU support (defaults to false for lightweight CPU build)
ARG USE_GPU=false

# Install PyTorch based on the USE_GPU argument
RUN if [ "$USE_GPU" = "true" ]; then \
        echo "Building with GPU support (CUDA 12.1)..."; \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121; \
    else \
        echo "Building with CPU-only support..."; \
        pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu; \
    fi

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Pre-download OCR models
RUN python preload_models.py

# Run application
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
