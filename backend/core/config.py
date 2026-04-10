import os
from typing import List

# Application Config
PORT = int(os.environ.get("PORT", 8080))

# Google Drive Config
DRIVE_FOLDER_ID = "1S2x4wTqO-9Lq_Q0Zp0Yk-9p15c1y-JvS"
SERVICE_ACCOUNT_FILE = "vr-saree-455416-654db90ca741.json"

# Database Configuration
CSV_FILENAME = "vr_database.csv"

# Batch Processing
BATCH_CONCURRENCY = min(32, (os.cpu_count() or 1) + 4)

# Feature Flags
ENABLE_BARCODE_SCANNER = True

# Security Limits
MAX_FILE_SIZE = 25 * 1024 * 1024       # 25 MB per file
MAX_TOTAL_SIZE = 200 * 1024 * 1024     # 200 MB total per upload batch
MAX_BATCH_SIZE = 100                   # Maximum 100 files per batch
MAX_IMAGE_DIMENSION = 8000             # Max width/height to prevent DecompressionBomb DOS
MAX_DOWNLOADS_PER_SESSION = 5          # Number of times a session ZIP can be downloaded

ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".webp"]
