# Saree Organizer

Automatic image sorting and renaming tool for Saree inventory. It scans images for "VR" barcodes or text (using OCR) and renames files to match their VR number (e.g., `VR12345.jpg`).

---

## 🚀 Deployment (Railway)

You can deploy both the frontend and backend to Railway using the same repository.

### 1. Backend Deployment
- **Plan**: Create a new service in Railway and link it to your GitHub repository.
- **Dockerfile**: Railway will automatically detect the main `Dockerfile`.
- **Environment Variables**:
  - `PORT`: (Automatically set by Railway)
  - `ENABLE_BARCODE_SCANNER`: Set to `False` (Recommended) to use OCR-only and avoid ZBar log noise. Set to `True` for faster barcode scanning if using high-quality images.
  - `ALLOWED_ORIGINS`: Set to your Railway frontend URL.

### 2. Frontend Deployment
- **Plan**: Create another service in the same Railway project and link it to the same repository.
- **Dockerfile**: You must tell Railway to use `Dockerfile.frontend`. You can do this in the service settings -> "Docker" -> "Dockerfile" field.
- **Environment Variables**:
  - `VITE_API_URL`: Set this to your **Railway Backend URL** (e.g., `https://backend-service.up.railway.app`).

---

## 🛠️ Scanning Configuration

The system supports two scanning modes:

1. **OCR-Primary (Default)**: Use the `ENABLE_BARCODE_SCANNER=False` flag. 
   - Uses AI-powered OCR (EasyOCR) to read the VR number.
   - Most reliable for varying image qualities.
   - Clean logs (avoids ZBar assertion warnings).

2. **Barcode-First**: Use the `ENABLE_BARCODE_SCANNER=True` flag.
   - Tries to find a standard barcode first (much faster).
   - Falls back to OCR if no barcode is found.
   - Requires high-quality, clear barcode images.

---

## 💻 Local Development

### Backend Setup
The backend requires system dependencies (`zbar`, `libgl`, etc.).

**Prerequisites:**
- Python 3.10+
- **Windows**: [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
- **Linux**: `apt-get install libzbar0 libgl1`

**Installation:**
```bash
python -m venv .venv
.\.venv\Scripts\activate  # Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend Setup
```bash
npm install
npm run dev
```

---

## 📦 Features
- **Smart Renaming**: Automatically handles duplicates and standardizes everything to "VRXXXXX" format.
- **Zip Downloads**: Process batches of images and download the results in a single organized ZIP.
- **Session Management**: Secure, temporary processing sessions with automatic cleanup.
