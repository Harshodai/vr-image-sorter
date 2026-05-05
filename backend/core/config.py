import os
import multiprocessing
from typing import List

# ---------------------------------------------------------------------------
# Application Config
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("PORT", 8080))

# Google Drive Config
DRIVE_FOLDER_ID = "1S2x4wTqO-9Lq_Q0Zp0Yk-9p15c1y-JvS"
SERVICE_ACCOUNT_FILE = "vr-saree-455416-654db90ca741.json"

# Database Configuration
CSV_FILENAME = "vr_database.csv"

# ---------------------------------------------------------------------------
# Intelligent defaults based on available CPU cores
# ---------------------------------------------------------------------------
_cpu_count: int = multiprocessing.cpu_count() or 1

# OCR Processing & Concurrency
# In Gunicorn multi-worker setups, each worker process gets its own pool.
# 1 engine per worker is highly recommended to prevent resource exhaustion and CPU thrashing.
OCR_POOL_SIZE: int = max(1, min(int(os.environ.get("OCR_POOL_SIZE", 1)), 8))

# How many images a single worker can queue/process in parallel.
# Even if OCR_POOL_SIZE is 1, a small queue (e.g., 2-4) allows the barcode
# scanner to run in parallel with the OCR engine.
_default_concurrency: int = min(OCR_POOL_SIZE * 4, 32)
BATCH_CONCURRENCY: int = max(1, min(int(os.environ.get("BATCH_CONCURRENCY", _default_concurrency)), 32))

# ---------------------------------------------------------------------------
# Request / Queue Management
# ---------------------------------------------------------------------------
# Maximum number of requests that can wait in the processing queue before
# the server starts returning 503 (backpressure).
REQUEST_QUEUE_SIZE: int = max(1, int(os.environ.get("REQUEST_QUEUE_SIZE", 100)))

# Per-image processing timeout in seconds (generous for OCR fallback path).
REQUEST_TIMEOUT: int = max(10, int(os.environ.get("REQUEST_TIMEOUT", 60)))

# ---------------------------------------------------------------------------
# Session Lifecycle
# ---------------------------------------------------------------------------
# How long (seconds) a session lives before it is eligible for cleanup.
SESSION_TTL: int = max(60, int(os.environ.get("SESSION_TTL", 3600)))

# How often (seconds) the background cleanup task runs.
CLEANUP_INTERVAL: int = max(30, int(os.environ.get("CLEANUP_INTERVAL", 300)))

# ---------------------------------------------------------------------------
# Feature Flags
# ---------------------------------------------------------------------------
ENABLE_BARCODE_SCANNER: bool = os.environ.get("ENABLE_BARCODE_SCANNER", "true").lower() not in ("0", "false", "no")
ENABLE_METRICS: bool = os.environ.get("ENABLE_METRICS", "true").lower() not in ("0", "false", "no")

# ---------------------------------------------------------------------------
# Security Limits
# ---------------------------------------------------------------------------
MAX_FILE_SIZE: int = int(os.environ.get("MAX_FILE_SIZE", 25 * 1024 * 1024))       # 25 MB per file
MAX_TOTAL_SIZE: int = int(os.environ.get("MAX_TOTAL_SIZE", 200 * 1024 * 1024))    # 200 MB total per upload batch
MAX_BATCH_SIZE: int = max(1, min(int(os.environ.get("MAX_BATCH_SIZE", 1000)), 1000))  # Up to 1000 files per batch
MAX_IMAGE_DIMENSION: int = int(os.environ.get("MAX_IMAGE_DIMENSION", 8000))        # Prevent DecompressionBomb DOS
MAX_DOWNLOADS_PER_SESSION: int = int(os.environ.get("MAX_DOWNLOADS_PER_SESSION", 5))

ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".webp"]

# ---------------------------------------------------------------------------
# Startup validation: catch misconfigured environments early
# ---------------------------------------------------------------------------
def _validate_config() -> None:
    errors: List[str] = []
    if OCR_POOL_SIZE < 1:
        errors.append("OCR_POOL_SIZE must be >= 1")
    if BATCH_CONCURRENCY < 1:
        errors.append("BATCH_CONCURRENCY must be >= 1")
    if MAX_BATCH_SIZE < 1:
        errors.append("MAX_BATCH_SIZE must be >= 1")
    if SESSION_TTL < 60:
        errors.append("SESSION_TTL must be >= 60 seconds")
    if REQUEST_TIMEOUT < 10:
        errors.append("REQUEST_TIMEOUT must be >= 10 seconds")
    if errors:
        raise ValueError("Configuration errors detected:\n" + "\n".join(f"  - {e}" for e in errors))

_validate_config()
