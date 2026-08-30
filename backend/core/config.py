import os
from typing import List

# Application Config
PORT = int(os.environ.get("PORT", 8080))

# Google Drive Config
DRIVE_FOLDER_ID = "1S2x4wTqO-9Lq_Q0Zp0Yk-9p15c1y-JvS"
SERVICE_ACCOUNT_FILE = "vr-saree-455416-654db90ca741.json"

# Database Configuration
CSV_FILENAME = "vr_database.csv"

# OCR Processing & Concurrency
#
# The app runs as a SINGLE worker process (see backend/Dockerfile) so that the
# in-memory session registry stays coherent. All throughput therefore comes
# from this in-process pool of OCR engines, one OS thread each.
#
# Measured on a 10-core host, 66 images, one engine per thread:
#     pool  2 -> 0.95 img/s     pool  7 -> 1.81 img/s  <- peak
#     pool  4 -> 1.52 img/s     pool  8 -> 1.47 img/s
#     pool  5 -> 1.77 img/s     pool 10 -> 1.27 img/s
#     pool  6 -> 1.78 img/s     pool 12 -> 1.26 img/s
# Throughput plateaus around 0.6x the core count and falls off after it, as
# engines start contending for cores and memory bandwidth. Roughly 45 MB
# resident per idle engine; ~2.4 GB peak while a batch is in flight.

def _auto_pool_size() -> int:
    """0.6x cores, floored at 2 and capped at 8 (past the measured plateau)."""
    cores = os.cpu_count() or 4
    return max(2, min(8, round(cores * 0.6)))

# OCR_POOL_SIZE=0 (or unset) means auto-size from the host's core count.
_configured_pool = int(os.environ.get("OCR_POOL_SIZE", 0))
OCR_POOL_SIZE = _configured_pool if _configured_pool > 0 else _auto_pool_size()

# Images in flight at once. Slightly above the engine count on purpose: images
# resolved by the barcode reader never acquire an engine, so a little
# oversubscription keeps the pool busy without making threads queue up.
BATCH_CONCURRENCY = int(os.environ.get("BATCH_CONCURRENCY", OCR_POOL_SIZE + 2))

# ONNX Runtime threads per OCR engine. Must stay at 1 whenever more than one
# worker process is running: ORT's default of -1 grabs every core per process,
# which makes extra workers contend instead of scale.
OCR_THREADS_PER_ENGINE = int(os.environ.get("OCR_THREADS_PER_ENGINE", 1))

# Accuracy gate
#
# A wrong rename is silent and permanent; a review is cheap. Anything the
# scanner is not sure about goes to a human rather than being guessed at.
#
# Measured on the sample set, every correct OCR read scored between 0.944 and
# 0.998 (median 0.996) and none required character substitution, so 0.90 is a
# floor with real headroom rather than an invented number. Raise it to send
# more borderline images to review; lower it only with labelled evidence.
OCR_MIN_CONFIDENCE = float(os.environ.get("OCR_MIN_CONFIDENCE", 0.88))

# A read at or above this confidence, with no character substitution, is taken
# as settled and stops the remaining rotations/sources.
# Must be STRICTLY above OCR_MIN_CONFIDENCE so reads that merely pass the
# acceptance floor continue through remaining rotations/sources, allowing
# multi-candidate aggregation and settlement ranking to complete.
OCR_EARLY_EXIT_CONFIDENCE = float(os.environ.get("OCR_EARLY_EXIT_CONFIDENCE", 0.95))
if OCR_EARLY_EXIT_CONFIDENCE <= OCR_MIN_CONFIDENCE:
    raise ValueError(
        f"OCR_EARLY_EXIT_CONFIDENCE ({OCR_EARLY_EXIT_CONFIDENCE}) must be strictly "
        f"greater than OCR_MIN_CONFIDENCE ({OCR_MIN_CONFIDENCE}). "
        "Reads that barely pass the acceptance floor must not trigger early exit."
    )

# Hard ceiling on a single image's scan.
SCAN_TIMEOUT_SECONDS = float(os.environ.get("SCAN_TIMEOUT_SECONDS", 60))

# Longest edge an image is scaled to before scanning.
MAX_SCAN_DIMENSION = int(os.environ.get("MAX_SCAN_DIMENSION", 1200))
ROI_TARGET_WIDTH = int(os.environ.get("ROI_TARGET_WIDTH", 800))

# Resolution used when a human explicitly retries an image. Higher than the
# default because retrying at the same resolution re-runs deterministic work
# and cannot produce a different answer.
RETRY_SCAN_DIMENSION = int(os.environ.get("RETRY_SCAN_DIMENSION", 2000))

# Feature Flags
ENABLE_BARCODE_SCANNER = os.environ.get("ENABLE_BARCODE_SCANNER", "True").lower() not in ("false", "0", "no")

# Security / Batch Limits
MAX_FILE_SIZE = 50 * 1024 * 1024       # 50 MB per file
MAX_TOTAL_SIZE = 1024 * 1024 * 1024    # 1 GB total per upload batch
MAX_BATCH_SIZE = 500                   # Maximum 500 files per chunk
MAX_IMAGE_DIMENSION = 8000             # Max width/height to prevent DecompressionBomb DOS
MAX_DOWNLOADS_PER_SESSION = int(os.environ.get("MAX_DOWNLOADS_PER_SESSION", 500))
MAX_ACCESS_COUNT_PER_SESSION = int(os.environ.get("MAX_ACCESS_COUNT_PER_SESSION", 1000000))

# How long a session's temp directory survives. A 100k-image run takes many
# hours, and the old 1-hour TTL expired sessions while their own upload was
# still in progress. 48h by default for the local single-PC deployment.
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", 48 * 3600))

ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".webp", ".jfif"]
