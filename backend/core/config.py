import os
import logging
from typing import List

logger = logging.getLogger("vr-saree-sorter.config")

# ---------------------------------------------------------------------------
# Application Config
# ---------------------------------------------------------------------------

PORT: int = int(os.environ.get("PORT", 8080))
"""HTTP port the uvicorn server listens on."""

# ---------------------------------------------------------------------------
# Google Drive Config
# ---------------------------------------------------------------------------

DRIVE_FOLDER_ID: str = "1S2x4wTqO-9Lq_Q0Zp0Yk-9p15c1y-JvS"
SERVICE_ACCOUNT_FILE: str = "vr-saree-455416-654db90ca741.json"

# ---------------------------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------------------------

CSV_FILENAME: str = "vr_database.csv"

# ---------------------------------------------------------------------------
# OCR Processing & Concurrency
# ---------------------------------------------------------------------------

OCR_POOL_SIZE: int = int(os.environ.get("OCR_POOL_SIZE", 2))
"""Number of RapidOCR engine instances kept alive in the pool.
Each engine is CPU-bound; set this to roughly (CPU cores / 2).
Range: 1–8. Validated at startup."""

_batch_concurrency_default = OCR_POOL_SIZE * 4
BATCH_CONCURRENCY: int = int(os.environ.get("BATCH_CONCURRENCY", _batch_concurrency_default))
"""Maximum number of images processed concurrently across the whole worker.
I/O-bound tasks (file writes, barcode decoding) can safely exceed OCR_POOL_SIZE.
Recommended: OCR_POOL_SIZE * 4. Range: 1–32. Must be >= OCR_POOL_SIZE."""

WORKER_TIMEOUT: int = int(os.environ.get("WORKER_TIMEOUT", 120))
"""Per-image processing timeout in seconds. Range: 30–300."""

# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

SESSION_TTL: int = int(os.environ.get("SESSION_TTL", 3600))
"""Seconds before an idle session is expired and its temp files deleted.
Range: 300–86400 (5 min to 24 hours)."""

SESSION_CLEANUP_INTERVAL: int = int(os.environ.get("SESSION_CLEANUP_INTERVAL", 300))
"""How often (seconds) the background cleanup task runs.
Range: 60–3600 (1 min to 1 hour)."""

MAX_CONCURRENT_SESSIONS: int = int(os.environ.get("MAX_CONCURRENT_SESSIONS", 1000))
"""Hard cap on simultaneous live sessions to prevent unbounded memory growth.
Range: 10–10000."""

# ---------------------------------------------------------------------------
# Resource Limits
# ---------------------------------------------------------------------------

MAX_MEMORY_PERCENT: int = int(os.environ.get("MAX_MEMORY_PERCENT", 80))
"""Percentage of system RAM at which a warning is emitted and new requests
may be rejected. Range: 50–95."""

# ---------------------------------------------------------------------------
# Feature Flags
# ---------------------------------------------------------------------------

ENABLE_BARCODE_SCANNER: bool = os.environ.get("ENABLE_BARCODE_SCANNER", "true").lower() == "true"
"""Toggle the zxing-cpp barcode scanning stage."""

ENABLE_MEMORY_POOLING: bool = os.environ.get("ENABLE_MEMORY_POOLING", "true").lower() == "true"
"""Reuse numpy/image buffers where possible to reduce GC pressure."""

# ---------------------------------------------------------------------------
# Security / Upload Limits
# ---------------------------------------------------------------------------

MAX_FILE_SIZE: int = 25 * 1024 * 1024
"""Maximum size of a single uploaded file (25 MB)."""

MAX_TOTAL_SIZE: int = 200 * 1024 * 1024
"""Maximum combined size of all files in one upload batch (200 MB)."""

MAX_BATCH_SIZE: int = int(os.environ.get("MAX_BATCH_SIZE", 1000))
"""Maximum number of files accepted in a single /api/process request.
Range: 1–5000."""

MAX_IMAGE_DIMENSION: int = int(os.environ.get("MAX_IMAGE_DIMENSION", 8000))
"""Maximum pixel width or height; larger images are rejected to prevent
DecompressionBomb DoS attacks."""

MAX_DOWNLOADS_PER_SESSION: int = 5
"""How many times a session ZIP may be downloaded before the link expires."""

ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".webp"]
"""Whitelist of accepted image file extensions."""


def log_config() -> None:
    """Emit all resolved configuration values at INFO level on startup."""
    logger.info("=== Configuration ===")
    logger.info("  PORT                    = %s", PORT)
    logger.info("  OCR_POOL_SIZE           = %s", OCR_POOL_SIZE)
    logger.info("  BATCH_CONCURRENCY       = %s", BATCH_CONCURRENCY)
    logger.info("  WORKER_TIMEOUT          = %ss", WORKER_TIMEOUT)
    logger.info("  MAX_BATCH_SIZE          = %s", MAX_BATCH_SIZE)
    logger.info("  MAX_FILE_SIZE           = %sMB", MAX_FILE_SIZE // (1024 * 1024))
    logger.info("  MAX_TOTAL_SIZE          = %sMB", MAX_TOTAL_SIZE // (1024 * 1024))
    logger.info("  MAX_IMAGE_DIMENSION     = %spx", MAX_IMAGE_DIMENSION)
    logger.info("  SESSION_TTL             = %ss", SESSION_TTL)
    logger.info("  SESSION_CLEANUP_INTERVAL= %ss", SESSION_CLEANUP_INTERVAL)
    logger.info("  MAX_CONCURRENT_SESSIONS = %s", MAX_CONCURRENT_SESSIONS)
    logger.info("  MAX_MEMORY_PERCENT      = %s%%", MAX_MEMORY_PERCENT)
    logger.info("  ENABLE_BARCODE_SCANNER  = %s", ENABLE_BARCODE_SCANNER)
    logger.info("  ENABLE_MEMORY_POOLING   = %s", ENABLE_MEMORY_POOLING)
    logger.info("=====================")
