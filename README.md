# 🥻 Saree Organizer

**Automated Image Sorting & Text Recognition Engine**

Saree Organizer is a production-ready tool designed to automate the painful process of inventory management. It uses AI-powered OCR and Barcode recognition to scan saree labels, extract "VR" identification numbers, and organize thousands of images into perfectly named folders in seconds.

---

## 📖 Project Documentation

If you have specific architectural questions, jump straight to the source:
- **"How do the frontend and backend deploy independently with isolated Docker contexts?"** ➡️ [Read Container Architecture](./ARCHITECTURE.md)
- **"How do the Barcode and OCR paths differ?"** ➡️ [Read Scanning Strategies](./CODE_FLOW.md#fast-pathslow-path)
- **"How does the system prevent memory leaks during RapidOCR scanning?"** ➡️ [Read Memory Efficiency Details](./CODE_FLOW.md#memory-efficiency)
- **"How do I configure scanning modes?"** ➡️ [View Scanning Configuration](./ARCHITECTURE.md#️-scanning-configuration)

---

## 🚀 Deployment (Railway)

### 1. Backend Service
- **Source**: Link your GitHub repo.
- **Root Directory**: **MUST** be set to `/backend` in Railway settings (Settings > Service > Root Directory) to ensure correct Docker context and `.dockerignore` targeting.
- **Dockerfile**: Automatically uses `Dockerfile` (once Root Directory is set).
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

**macOS / Linux**
```bash
make doctor   # check prerequisites
make setup    # venv + Python deps + OCR models + npm deps
make dev      # backend :8000 + frontend :8080
```

**Windows** (PowerShell or cmd — same target names)
```
.\make.cmd doctor
.\make.cmd setup
.\make.cmd dev
```

`make setup` uses [uv](https://github.com/astral-sh/uv) when it is installed,
which cuts the Python install from minutes to seconds. Install it with
`winget install astral-sh.uv` on Windows or `brew install uv` on macOS.

Run `make help` / `.\make.cmd help` for the full target list
(`up`/`down` for Docker, `test` for the accuracy check, `bench` for timing,
`dist` to build the distributable zip).

### Tuning throughput
The backend runs as a **single** worker process; concurrency comes from an
in-process pool of OCR engines sized automatically from the host's core count
(`0.6x cores`, floored at 2, capped at 8). Override with `OCR_POOL_SIZE`.
Do not raise `WEB_WORKERS` above 1 — upload sessions are held in process
memory, so extra workers silently lose chunks of large uploads.

---

## ✨ Features
- 🧠 **AI-Powered**: Uses RapidOCR with orientation-detection for 99% accuracy on hand-held photos.
- ⚡ **Optimized**: Early-exit logic ensures high-speed processing (scans only what is needed).
- 🔒 **Secure**: Temporary processing sessions with HMAC-signed download links.
- 📦 **Batch Processing**: Upload hundreds of images; get a clean ZIP back instantly.
