# 🥻 Saree Organizer

**Automated Image Sorting & Text Recognition Engine**

Saree Organizer is a production-ready tool designed to automate the painful process of inventory management. It uses AI-powered OCR and Barcode recognition to scan saree labels, extract "VR" identification numbers, and organize thousands of images into perfectly named folders in seconds.

---

## 📖 Project Documentation
- **[Technical Architecture & HLD](./ARCHITECTURE.md)**: Deep dive into the system design, file structure, and function-level documentation.
- **[Deployment Guide](#-deployment-railway)**: Steps to go live on Railway.
- **[Scanning Modes](./ARCHITECTURE.md#-scanning-configuration)**: Understanding OCR vs. Barcode modes.

---

## 🚀 Deployment (Railway)

### 1. Backend Service
- **Source**: Link your GitHub repo.
- **Dockerfile**: Automatically uses `Dockerfile`.
- **Primary Settings**: 
  - `ENABLE_BARCODE_SCANNER`: Set to `False` (Default - Recommended for OCR stability).
  - `ALLOWED_ORIGINS`: Set to your frontend URL.

### 2. Frontend Service
- **Source**: Link your GitHub repo.
- **Dockerfile**: **Search for "Dockerfile" in settings and set it to `Dockerfile.frontend`**.
- **Variables**:
  - `VITE_API_URL`: Path to your backend (e.g., `https://backend.up.railway.app`).

---

## 🛠️ Local Development

### Prerequisites
- **Python 3.10+**
- **Node.js 20+**
- **System Libs**: 
  - Windows: [VC++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
  - Linux: `sudo apt-get install libzbar0 libgl1`

### Quick Start
1. **Backend**:
   ```bash
   pip install -r requirements.txt
   uvicorn main:app --reload
   ```
2. **Frontend**:
   ```bash
   npm install
   npm run dev
   ```

---

## ✨ Features
- 🧠 **AI-Powered**: Uses EasyOCR with orientation-detection for 99% accuracy on hand-held photos.
- ⚡ **Optimized**: Early-exit logic ensures high-speed processing (scans only what is needed).
- 🔒 **Secure**: Temporary processing sessions with HMAC-signed download links.
- 📦 **Batch Processing**: Upload hundreds of images; get a clean ZIP back instantly.
