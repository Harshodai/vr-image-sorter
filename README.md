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
- **Python 3.9+** (3.12 recommended)
- **Node.js 20+**
- **System Libs**: 
  - Windows: [VC++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
  - Linux: `sudo apt-get install libzbar0 libgl1`

### Quick Start

**Single command (any platform, needs only Node + Python)**
```bash
npx github:Harshodai/vr-image-sorter doctor   # what is missing
npx github:Harshodai/vr-image-sorter setup    # install everything
npx github:Harshodai/vr-image-sorter start    # open http://localhost:8080
npx github:Harshodai/vr-image-sorter update   # pull latest, re-run setup
```

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

### Sorting a large backlog (100k images)

Do not do this through the browser — the tab has to hold every File object and
preview blob, and a crash loses the whole run. Use the folder mode: it reads
from disk, records progress after every image, and resumes where it stopped.

```bash
make sort   IN=./photos OUT=./sorted      # or: npx github:Harshodai/vr-image-sorter sort --input ... --output ...
make resume IN=./photos OUT=./sorted      # after an interruption
make watch  IN=./dropbox OUT=./sorted     # process files as they are dropped in
```

Add `SORT_ARGS=--copy` to leave the input folder untouched.

Results land in three folders, and the split is the point:

| folder | meaning |
|---|---|
| `renamed/` | confidently identified, renamed to `VR<digits>.<ext>` |
| `review/` | a code was read but not trusted — **keeps its original filename** |
| `failed/` | nothing readable — keeps its original filename |

Nothing in `review/` is ever renamed on a guess. Confirm those in the web UI
(magnify the label first), or in bulk via the spreadsheet:

```bash
# open sorted/review.csv, fill in the `corrected_code` column, then:
make apply OUT=./sorted
```

`manifest.jsonl` records every image with its code, confidence, method and the
reason it landed where it did — it is both the audit trail and the resume index.

### Accuracy model

A wrong rename is silent and permanent; a review is cheap. So an image is only
renamed automatically when the read is trustworthy. It is sent to review when:

- confidence is below `OCR_MIN_CONFIDENCE` (default 0.90 — correct reads on the
  sample set scored 0.944-0.998, so this has real headroom),
- the code only matched after `O`->`0` / `I`->`1` character substitution, which
  can rescue a genuine read or invent a plausible wrong one, or
- two different codes were both read confidently.

Barcodes (Code128/QR) carry their own checksums, so a successful barcode decode
is self-verifying and never needs review.

Tune with `OCR_MIN_CONFIDENCE` (higher = more review, fewer automatic renames)
and `OCR_EARLY_EXIT_CONFIDENCE` (lower = faster, less cross-checking).

### Tuning throughput
The backend runs as a **single** worker process; concurrency comes from an
in-process pool of OCR engines sized automatically from the host's core count
(`0.6x cores`, floored at 2, capped at 8). Override with `OCR_POOL_SIZE`.
Do not raise `WEB_WORKERS` above 1 — upload sessions are held in process
memory, so extra workers silently lose chunks of large uploads.

---

## ✨ Features
- 🧠 **Barcode first, OCR second**: Code128/QR decode is checksum-verified and fast;
  RapidOCR handles the rest, reading all four orientations.
- 🛑 **Never renames on a guess**: low-confidence, character-substituted or
  conflicting reads go to a review queue keeping their original filename.
- ⚡ **Early exit**: a clean high-confidence read stops the remaining passes, so
  only hard images pay for the full sweep.
- 🔒 **Secure**: temporary sessions with token-authenticated download links.
- 📁 **Folder mode**: resumable, disk-based processing for backlogs the browser
  cannot hold.

### Measured, not claimed
On the 22-image sample in this repo, on a 10-core host:

| | |
|---|---|
| auto-renamed correctly | 22/22 |
| wrong renames | 0 |
| throughput | 2.03 img/s at pool=6 |
| 100,000 images | ~13.7 h |

That is 22 images. It is evidence the pipeline works, **not** proof of an
accuracy rate at 100,000. Run `make test` against your own labelled set before
trusting a number, and expect to tune `OCR_MIN_CONFIDENCE` when you do.
