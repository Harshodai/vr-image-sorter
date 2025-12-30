
# VR Image Sorter

Automatic image sorting and renaming tool for Saree inventory. It scans images for "VR" barcodes or text (using OCR) and renames files to match their VR number (e.g., `VR12345.jpg`).

## Project Structure

- **Backend**: Python (FastAPI, OpenCV, EasyOCR, PyZBar). Handles image processing.
- **Frontend**: React (Vite, Tailwind). User interface for uploading and downloading.

## Backend Setup

### Option 1: Docker (Recommended for Deployment)
The backend requires system dependencies (`zbar`, `libgl`, etc.) which are pre-configured in the Dockerfile.

**Build and Run:**
```bash
docker build -t saree-backend .
docker run -p 8000:8000 saree-backend
```

**Deploy to Render:**
1. Connect your repo to [Render](https://render.com).
2. Create a **Web Service**.
3. Select **Docker** as the Runtime.
4. Render will automatically build and deploy using the `Dockerfile`.

### Option 2: Local Development
If running locally without Docker, you must install the required system libraries.

**Prerequisites:**
- Python 3.10+
- **Windows**: [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
- **Linux**: `apt-get install libzbar0 libgl1`

**Installation:**
```bash
# Create virtual environment
python -m venv .venv

# Activate it (Windows)
.\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

**Run Server:**
```bash
uvicorn main:app --reload --port 8000
```
Server runs at: `http://localhost:8000`

## Frontend Setup

The frontend is a standard Vite React app.

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

## API Usage

- **Endpoint**: `POST /api/process`
- **Body**: Multipart form-data with `files` (list of images).
- **Response**: JSON with processed filenames and download URL.

## Features
- **Hybrid Scanning**: Tries fast barcode scanning first, falls back to AI-powered OCR (EasyOCR).
- **Robustness**: Handles rotated images, noise, and partial blurs.
- **Bulk Processing**: Upload multiple images at once.
