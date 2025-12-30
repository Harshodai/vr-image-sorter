
FROM python:3.13-slim

# Install system dependencies including those for OpenCV and ZBar
# libgl1-mesa-glx: for OpenGL support
# libglib2.0-0, libsm6, libxext6, libxrender-dev: common cv2 dependencies
# libzbar0: for pyzbar
RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
