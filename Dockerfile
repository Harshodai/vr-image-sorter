
FROM python:3.13-slim

# Install system dependencies including those for OpenCV and ZBar
# libgl1-mesa-glx: for OpenGL support
# libglib2.0-0, libsm6, libxext6, libxrender-dev: common cv2 dependencies
# libzbar0: for pyzbar
RUN apt-get update && apt-get install -y \
    build-essential \
    libzbar0 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install CPU-only PyTorch (much smaller, fixes Render timeout/RAM issues)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Copy requirements and install remaining dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Pre-download OCR models to avoid runtime download
RUN python preload_models.py

# Command to run the application using Render's PORT or default to 8000
CMD sh -c "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"
