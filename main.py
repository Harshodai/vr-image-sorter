from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import cv2
import numpy as np
from pyzbar.pyzbar import decode
import easyocr
import re
import os
import tempfile
import shutil
import zipfile
from typing import List, Optional
import uuid
import time
from fastapi import BackgroundTasks
from PIL import Image
import io
import logging
import secrets
import hashlib
import hmac
from pathlib import Path
import sys
from pyzbar.pyzbar import ZBarSymbol, decode
import asyncio
import gc
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import asynccontextmanager

# Configure logging - server-side only, no sensitive details exposed
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Sized to match CPU cores available per worker (2 threads per worker)
_executor = ThreadPoolExecutor(max_workers=int(os.getenv("SCAN_THREADS", "2")))

# Dedicated single-thread executor for individual readtext() calls so we can
# enforce a hard timeout via Future.result(timeout=...) without blocking the
# main scan thread indefinitely.
_ocr_executor = ThreadPoolExecutor(max_workers=int(os.getenv("SCAN_THREADS", "2")))

async def scan_in_thread(sorter_instance, image_bytes):
    """Run CPU-heavy scanning in a thread pool so it doesn't block the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, sorter_instance.scan_barcode_from_bytes, image_bytes)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Eagerly load the OCR model at startup instead of lazy loading on first request
    # This prevents the first user from experiencing a 10-30s delay
    logger.info("Pre-loading OCR model into memory...")
    sorter.get_reader()
    logger.info("OCR model loaded successfully")
    yield
    # Cleanup on shutdown
    _executor.shutdown(wait=False)
    _ocr_executor.shutdown(wait=False)
    logger.info("Shutting down")


app = FastAPI(title="Saree Organizer API", lifespan=lifespan)
# Global exception handler - returns generic error messages to clients
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unexpected error processing request: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An error occurred processing your request"}
    )

# Security: File upload limits
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file
MAX_BATCH_SIZE = 1000  # Maximum files per batch
MAX_TOTAL_SIZE = 2000 * 1024 * 1024  # 2000MB total per request
MAX_IMAGE_DIMENSION = 10000  # Maximum width/height in pixels
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Security: Session limits
SESSION_TIMEOUT = 1800  # 30 minutes
MAX_DOWNLOADS_PER_SESSION = 500  # Increased to allow for individual file downloads

# Configuration: Scanning methods
# Set to True only if you have high-quality barcode images and want faster scanning.
# Defaults to False because ZBar can be noisy and unreliable for some images.
ENABLE_BARCODE_SCANNER = os.getenv("ENABLE_BARCODE_SCANNER", "True").lower() == "true"

# Configuration: Batch concurrency
# Limits how many files are scanned simultaneously to prevent CPU saturation.
# Increase if the host has more cores; lower if you see high CPU contention.
BATCH_CONCURRENCY = int(os.getenv("BATCH_CONCURRENCY", "2"))

# Configuration: OCR timeout
# Maximum seconds to wait for a single reader.readtext() call before giving up.
# EasyOCR can hang indefinitely on certain corrupted or unusual images; this
# cap prevents one bad image from blocking the entire batch.
# Increase if you have very large, high-resolution images that legitimately need
# more time; decrease for faster (but potentially less thorough) scanning.
OCR_TIMEOUT_SECONDS = int(os.getenv("OCR_TIMEOUT_SECONDS", "10"))

# CORS: Use environment variable for allowed origins (security fix)
# We check both ALLOWED_ORIGINS and ALLOWED_DOMAINS to be forgiving of common naming conventions
# Added your specific Railway frontend as a hardcoded fallback
allowed_origins_env = os.getenv("ALLOWED_ORIGINS") or os.getenv("ALLOWED_DOMAINS") or "https://vaarahi-barcode-scanner.up.railway.app,http://localhost:8080,http://localhost:5173,https://lovable.dev"
# Robust parsing: split by comma, strip whitespace, and remove trailing slashes
allowed_origins = [origin.strip().rstrip("/") for origin in allowed_origins_env.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Store temp directories with timestamp for cleanup
temp_dirs = {}


def generate_session_token():
    """Generate a cryptographically secure session token"""
    return secrets.token_urlsafe(32)


def validate_session_token(session_id: str, authorization: Optional[str]) -> dict:
    """Validate session exists and token is correct"""
    if session_id not in temp_dirs:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = temp_dirs[session_id]
    
    # Check if session expired
    if time.time() - session["created_at"] > SESSION_TIMEOUT:
        cleanup_session(session_id)
        raise HTTPException(status_code=410, detail="Session expired")
    
    # Require Bearer token
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = authorization.split(" ", 1)[1]
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(session["token_hash"], token_hash):
        raise HTTPException(status_code=403, detail="Invalid session token")
    
    return session


def validate_filename(filename: str) -> str:
    """Validate filename to prevent path traversal attacks"""
    # Get just the base filename, removing any path components
    safe_filename = os.path.basename(filename)
    
    # Reject if the original filename contained path components
    if safe_filename != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Reject path traversal patterns
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    # Reject empty or suspicious filenames
    if not safe_filename or safe_filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    return safe_filename


def validate_session_id(session_id: str) -> str:
    """Validate session_id format to prevent path traversal"""
    # Session IDs should be valid UUIDs
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    
    # Additional safety check
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        raise HTTPException(status_code=400, detail="Invalid session ID")
    
    return session_id


def cleanup_session(session_id: str):
    """Refactored cleanup logic"""
    if session_id in temp_dirs:
        path = temp_dirs[session_id]["path"]
        try:
            if os.path.exists(path):
                shutil.rmtree(path)
            logger.info("Cleaned up session %s", session_id)
        except Exception as e:
            logger.error("Error cleaning up session %s: %s", session_id, e)
        finally:
            del temp_dirs[session_id]

class SareeSorter:
    def __init__(self):
        self.reader = None # Lazy load

    def get_reader(self):
        if self.reader is None:
            logger.info("Initializing OCR Reader")
            # verbose=False prevents encoding errors on Windows console
            self.reader = easyocr.Reader(['en'], verbose=False) 
        return self.reader

    def setup_directories(self):
        # API handles directories in endpoints, but keeping for compatibility if needed
        pass

    def preprocess_image(self, image, method):
        if method == "original":
            return image
        
        # Convert to grayscale if needing processing
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        if method == "grayscale":
            return gray
        
        if method == "sharpen":
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            return cv2.filter2D(gray, -1, kernel)
        
        if method == "threshold_otsu":
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return thresh
        
        if method == "adaptive_threshold":
            return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        
        if method == "clahe":
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(gray)

        return gray

    # ── Label Region Detection (the key innovation) ─────────────────────
    def detect_label_regions(self, image):
        """
        Detect white/light rectangular label stickers in the image.
        Returns a list of cropped, perspective-corrected label images
        sorted by area (largest first).
        
        Strategy: White paper labels have LOW saturation compared to
        colored fabric. We try progressively wider saturation thresholds
        and pick the tightest one that finds valid label candidates.
        """
        h, w = image.shape[:2]
        img_area = h * w
        
        # Convert to HSV — saturation is our primary discriminator
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]  # saturation channel
        val = hsv[:, :, 2]  # value channel
        
        # Progressive saturation thresholds: tight first, then widen.
        # White paper: S typically < 20. Slightly off-white: S < 40.
        # We also require minimum brightness (V > 120) to exclude shadows.
        threshold_configs = [
            (25, 120),   # Tight: very white labels
            (40, 120),   # Medium: slightly tinted labels  
            (60, 140),   # Wide: off-white or aged labels
        ]
        
        for s_max, v_min in threshold_configs:
            mask = np.zeros((h, w), dtype=np.uint8)
            mask[(sat < s_max) & (val > v_min)] = 255
            
            # Morphological operations to merge nearby white patches (text gaps)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            # Remove small noise
            kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_small)
            
            label_crops = self._extract_label_crops(image, mask, img_area)
            if label_crops:
                logger.debug(
                    "Label detection hit at S<%d V>%d: %d candidates",
                    s_max, v_min, len(label_crops)
                )
                return label_crops
        
        logger.debug("No label regions found at any threshold")
        return []

    def _extract_label_crops(self, image, mask, img_area):
        """Extract perspective-corrected label crops from a binary mask."""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        label_crops = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            # Label should be between 0.5% and 25% of image area
            if not (img_area * 0.005 < area < img_area * 0.25):
                continue
            
            # Get minimum area rotated rectangle
            rect = cv2.minAreaRect(cnt)
            box = cv2.boxPoints(rect)
            box = np.intp(box)
            
            # Check aspect ratio — labels are roughly rectangular (1:1 to 1:4)
            rect_w, rect_h = rect[1]
            if rect_w == 0 or rect_h == 0:
                continue
            aspect = max(rect_w, rect_h) / min(rect_w, rect_h)
            if aspect > 5.0:
                continue
            
            # Perspective-correct the crop
            src_pts = box.astype(np.float32)
            src_pts = self._order_points(src_pts)
            
            dst_w = int(max(rect_w, rect_h))
            dst_h = int(min(rect_w, rect_h))
            if dst_w < 50 or dst_h < 30:
                continue
            
            dst_pts = np.array([
                [0, 0],
                [dst_w - 1, 0],
                [dst_w - 1, dst_h - 1],
                [0, dst_h - 1]
            ], dtype=np.float32)
            
            M = cv2.getPerspectiveTransform(src_pts, dst_pts)
            warped = cv2.warpPerspective(image, M, (dst_w, dst_h))
            
            # Add white padding for better barcode reading
            pad = 10
            padded = cv2.copyMakeBorder(warped, pad, pad, pad, pad,
                                         cv2.BORDER_CONSTANT, value=(255, 255, 255))
            
            label_crops.append((area, padded))
        
        # Sort by area descending (largest label first)
        label_crops.sort(key=lambda x: x[0], reverse=True)
        return [crop for _, crop in label_crops]

    @staticmethod
    def _order_points(pts):
        """Order 4 points as: top-left, top-right, bottom-right, bottom-left."""
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]   # top-left has smallest sum
        rect[2] = pts[np.argmax(s)]   # bottom-right has largest sum
        d = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(d)]   # top-right has smallest diff
        rect[3] = pts[np.argmax(d)]   # bottom-left has largest diff
        return rect

    # ── Enhanced Barcode Decoding ────────────────────────────────────────
    def _upscale_if_small(self, image, min_width=800):
        """Upscale image if it's too small for reliable barcode reading."""
        h, w = image.shape[:2]
        if w < min_width:
            scale = min_width / w
            new_w = int(w * scale)
            new_h = int(h * scale)
            return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        return image

    def decode_barcode_robust(self, image):
        """
        Try to decode a barcode from an image using multiple strategies:
        upscaling, preprocessing, and rotation.
        """
        if not ENABLE_BARCODE_SCANNER:
            return None

        # Safe symbol types to avoid DataBar assertion crashes
        symbols = [
            ZBarSymbol.CODE128,
            ZBarSymbol.QRCODE,
            ZBarSymbol.CODE39,
            ZBarSymbol.EAN13,
            ZBarSymbol.I25,
        ]
        
        # Try at multiple scales
        scales = [1.0]
        h, w = image.shape[:2]
        
        # Aggressive upscaling for tiny crops from low-res images
        if w < 200:
            scales = [5.0, 4.0, 3.0]
        elif w < 400:
            scales = [3.0, 2.0]
        elif w < 800:
            scales = [2.0, 3.0, 1.0]
        elif w < 1200:
            scales = [1.5, 1.0]
        
        # Methods include new "sharpen_heavy" which works well with Lanczos4 upscaling
        methods = ["original", "grayscale", "threshold_otsu", "sharpen", "clahe", "sharpen_heavy"]
        rotations = [0, 180, 90, 270]  # 180 first since labels are often upside-down
        
        # Strong sharpening kernel that reconstructs blurry barcode edges
        strong_sharpen_kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        
        for scale in scales:
            if scale != 1.0:
                # LANCZOS4 is critical for preserving hard edges in barcodes during upscale
                scaled = cv2.resize(image, None, fx=scale, fy=scale,
                                     interpolation=cv2.INTER_LANCZOS4)
            else:
                scaled = image
            
            for method in methods:
                if method == "sharpen_heavy":
                    processed = cv2.filter2D(scaled, -1, strong_sharpen_kernel)
                    # Apply Otsu thresholding after heavy sharpening
                    gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
                    _, processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                else:
                    processed = self.preprocess_image(scaled, method)
                
                for angle in rotations:
                    if angle == 0:
                        img_to_scan = processed
                    elif angle == 90:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_CLOCKWISE)
                    elif angle == 180:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_180)
                    else:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    
                    try:
                        barcodes = decode(img_to_scan, symbols=symbols)
                        for barcode in barcodes:
                            barcode_data = barcode.data.decode("utf-8")
                            if barcode_data:
                                logger.debug(
                                    "Barcode found: scale=%.1f method=%s angle=%d data=%s",
                                    scale, method, angle, barcode_data
                                )
                                return barcode_data
                    except Exception as e:
                        logger.debug("Barcode scan error: %s", str(e))
        
        return None

    # ── Legacy decode_frame (kept for compatibility) ────────────────────
    def decode_frame(self, image):
        if not ENABLE_BARCODE_SCANNER:
            return None
        symbols = [
            ZBarSymbol.CODE128,
            ZBarSymbol.QRCODE,
            ZBarSymbol.CODE39,
            ZBarSymbol.EAN13,
            ZBarSymbol.I25
        ]
        try:
            barcodes = decode(image, symbols=symbols)
            for barcode in barcodes:
                barcode_data = barcode.data.decode("utf-8")
                if barcode_data:
                    return barcode_data
        except Exception as e:
            logger.debug("Barcode scan error: %s", str(e))
        return None

    # ── Enhanced OCR ────────────────────────────────────────────────────
    def scan_ocr(self, image, roi_image=None):
        """
        Run OCR to find VR codes.
        If roi_image is provided, scan that first (label crop).
        Falls back to full image if roi_image fails.
        """
        try:
            reader = self.get_reader()
            
            # If we have a label crop, try it first (much faster & more accurate)
            images_to_try = []
            if roi_image is not None:
                # Upscale small ROI crops for better OCR accuracy
                roi_upscaled = self._upscale_if_small(roi_image, min_width=600)
                images_to_try.append(("roi", roi_upscaled))
            images_to_try.append(("full", image))
            
            for source_name, img in images_to_try:
                result = self._ocr_with_rotations(reader, img)
                if result:
                    logger.debug("OCR match found from %s source", source_name)
                    return result
            
            logger.debug("No OCR match found after all variations")
        except Exception as e:
            logger.error("OCR processing error: %s", type(e).__name__)
        return None

    @staticmethod
    def _clean_ocr_text(text):
        """
        Aggressively clean OCR text for VR code extraction.
        OCR often reads VR221130 as 'Vr?21'Jo' or 'VRP' with garbled chars.
        """
        # Step 1: Remove spaces and uppercase
        clean = text.replace(" ", "").upper()
        # Step 2: Fix common OCR letter→digit confusions BEFORE stripping
        ocr_digit_map = str.maketrans("OoIl|", "00111")
        clean = clean.translate(ocr_digit_map)
        # Step 3: Strip ALL non-alphanumeric characters (?, ', -, etc.)
        clean = re.sub(r"[^A-Z0-9]", "", clean)
        return clean

    def _ocr_with_rotations(self, reader, image):
        """Try OCR across rotations and preprocessing methods."""
        rotations = [0, 180, 90, 270]  # 180 prioritized for upside-down labels
        methods = ["grayscale", "clahe", "threshold_otsu", "original"]
        best_match = None
        
        for method in methods:
            for angle in rotations:
                if angle == 0:
                    rotated = image
                elif angle == 90:
                    rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
                elif angle == 180:
                    rotated = cv2.rotate(image, cv2.ROTATE_180)
                else:
                    rotated = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

                img_to_scan = self.preprocess_image(rotated, method)

                # Submit readtext() to a dedicated executor so we can enforce a
                # hard deadline. EasyOCR occasionally hangs indefinitely on
                # corrupted or unusual images; the timeout prevents one bad
                # image from blocking the entire batch.
                try:
                    future = _ocr_executor.submit(reader.readtext, img_to_scan)
                    results = future.result(timeout=OCR_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    h, w = img_to_scan.shape[:2] if hasattr(img_to_scan, "shape") else (0, 0)
                    logger.warning(
                        "OCR timed out after %ds (angle=%d method=%s size=%dx%d) — skipping OCR for this image",
                        OCR_TIMEOUT_SECONDS, angle, method, w, h,
                    )
                    return None

                # Strategy 1: Check individual text boxes for VR codes
                for (bbox, text, prob) in results:
                    clean = self._clean_ocr_text(text)
                    if "VR" in clean:
                        # Try strict match first: VR followed by 2 to 8 digits (prevent matching long MRP/Phone numbers)
                        match = re.search(r"VR\d{2,8}(?!\d)", clean)
                        if match and (best_match is None or len(match.group(0)) > len(best_match)):
                            logger.debug(
                                "OCR match at angle %d method %s: %s (from box: '%s' -> '%s')",
                                angle, method, match.group(0), text, clean
                            )
                            best_match = match.group(0)
                        
                        # Fuzzy match: VR followed by digits with possible letter noise
                        if not match or len(match.group(0)) < 5:
                            # Extract everything after "VR" and keep only digits
                            vr_idx = clean.index("VR")
                            after_vr = clean[vr_idx + 2:]
                            # Collect leading digit-like characters
                            digits = ""
                            for ch in after_vr:
                                if ch.isdigit():
                                    digits += ch
                                elif len(digits) >= 3:
                                    # Stop if we've collected enough digits and hit a letter
                                    break
                                # Skip isolated letters within digit sequence (OCR noise)
                            if len(digits) >= 4:
                                candidate = f"VR{digits}"
                                if best_match is None or len(candidate) > len(best_match):
                                    logger.debug(
                                        "OCR fuzzy match at angle %d method %s: %s (from: '%s')",
                                        angle, method, candidate, clean
                                    )
                                    best_match = candidate

            # If Strategy 1 found a valid, complete VR code (e.g. at least VR + 4 digits), SKIP Strategy 2 
            # to prevent concatenating unwanted MRP numbers or phone numbers
            if best_match and len(best_match) >= 6:
                return best_match
                
            # Strategy 2: Concatenate all text boxes and search
            # This catches cases where OCR splits "VR221130" into "VR22" + "1130"
            all_text = "".join(self._clean_ocr_text(t) for _, t, _ in results)
            if "VR" in all_text:
                # Strict concat match: limit digits to avoid grabbing MRP
                concat_match = re.search(r"VR\d{4,8}(?!\d)", all_text)
                if concat_match and (best_match is None or len(concat_match.group(0)) > len(best_match)):
                    logger.debug(
                        "OCR concat match at angle %d method %s: %s (from: '%s')",
                        angle, method, concat_match.group(0), all_text
                    )
                    best_match = concat_match.group(0)
                
                # Fuzzy concat: extract digits after VR
                    vr_idx = all_text.index("VR")
                    after_vr = all_text[vr_idx + 2:]
                    digits = ""
                    for ch in after_vr:
                        if ch.isdigit():
                            digits += ch
                        elif len(digits) >= 3:
                            break
                    if len(digits) >= 4:
                        candidate = f"VR{digits}"
                        if best_match is None or len(candidate) > len(best_match):
                            logger.debug(
                                "OCR fuzzy concat match at angle %d method %s: %s",
                                angle, method, candidate
                            )
                            best_match = candidate

                # If we found a sufficiently long match (5+ digits), return immediately
                if best_match and len(best_match) >= 7:  # "VR" + 5+ digits
                    logger.debug("OCR returning high-confidence match: %s", best_match)
                    return best_match

        # Reject dangerously short partial matches (e.g. "VR22" instead of "VR221130")
        if best_match and len(best_match) < 6:
            logger.debug("Rejecting partial VR match '%s' (too short)", best_match)
            return None
            
        return best_match

    # ── Main Entry Point (Label-First Architecture) ─────────────────────
    def scan_barcode_from_bytes(self, image_bytes) -> Optional[str]:
        """
        Attempts to scan a barcode/VR code from image bytes.
        Uses a label-first strategy: detect the label sticker, crop it,
        then run barcode + OCR on the clean crop.
        """
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            original_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if original_image is None:
                logger.warning("Could not decode image bytes")
                return None
        except Exception as e:
            logger.error("Image decoding error: %s", type(e).__name__)
            return None

        # ── Step 1: Detect label regions ─────────────────────────────
        label_crops = self.detect_label_regions(original_image)
        logger.debug("Detected %d label regions", len(label_crops))
        
        # ── Step 2: Try barcode on each label crop ───────────────────
        # NOTE: Only run pyzbar on clean label crops, NOT on the full
        # image. pyzbar on noisy fabric images produces false positives.
        for i, crop in enumerate(label_crops):
            result = self.decode_barcode_robust(crop)
            if result:
                logger.info("Barcode found on label crop %d", i)
                return result
        
        # ── Step 3: Try OCR on label crops first, then full image ────
        logger.debug("Attempting OCR fallback")
        best_roi = label_crops[0] if label_crops else None
        ocr_result = self.scan_ocr(original_image, roi_image=best_roi)
        if ocr_result:
            return ocr_result
        
        # ── Step 4: If first crop failed OCR, try remaining crops ────
        if len(label_crops) > 1:
            for crop in label_crops[1:]:
                ocr_result = self.scan_ocr(crop)
                if ocr_result:
                    return ocr_result

        return None

    def standardize_filename(self, barcode_data):
        clean_data = barcode_data.strip()
        if not clean_data.upper().startswith("VR"):
            if clean_data.isdigit():
                 return f"VR{clean_data}"
        return clean_data.upper()

# Global sorter instance
sorter = SareeSorter()

@app.post("/api/process")
async def process_images(files: List[UploadFile] = File(...)):
    # Security: Validate batch size
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_BATCH_SIZE} files allowed per request"
        )
    
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    
    # Security: Validate all files before processing
    validated_files = []
    total_size = 0
    
    for file in files:
        # Validate file extension
        ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type for '{file.filename}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        
        # Read and validate file size
        contents = await file.read()
        file_size = len(contents)
        
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' exceeds maximum size of {MAX_FILE_SIZE // (1024*1024)}MB"
            )
        
        total_size += file_size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Total upload size exceeds {MAX_TOTAL_SIZE // (1024*1024)}MB limit"
            )
        
        # Validate it's actually a valid image
        try:
            image = Image.open(io.BytesIO(contents))
            image.verify()
            # Re-open after verify() as it closes the file
            image = Image.open(io.BytesIO(contents))
            
            # Check dimensions to prevent huge images
            if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
                raise HTTPException(
                    status_code=400,
                    detail=f"Image '{file.filename}' dimensions exceed {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} limit"
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid or corrupted image: '{file.filename}'"
            )
        
        validated_files.append({"filename": file.filename, "contents": contents, "ext": ext})
    
    # All files validated, now process
    session_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    output_dir = os.path.join(temp_dir, "output")
    os.makedirs(output_dir)
    
    processed = []
    failed = []
    
    # Create failed directory for storing failed images
    failed_dir = os.path.join(temp_dir, "failed")
    os.makedirs(failed_dir)
    
    batch_size = len(validated_files)
    logger.info("Batch processing started: %d file(s), concurrency limit=%d", batch_size, BATCH_CONCURRENCY)
    batch_start = time.monotonic()

    # One semaphore per request — limits simultaneous CPU-heavy scans to
    # BATCH_CONCURRENCY slots, preventing CPU saturation on large batches.
    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def _process_one(file_data):
        contents = file_data["contents"]
        filename = file_data["filename"]
        ext = file_data["ext"]
        safe_filename = validate_filename(filename)
        
        try:
            # Acquire semaphore only around the CPU-intensive scan, not I/O
            async with semaphore:
                file_start = time.monotonic()
                result = await scan_in_thread(sorter, contents)
                elapsed = time.monotonic() - file_start
                logger.info("File scanned in %.2fs: %s", elapsed, safe_filename)
                # Prompt release of CV/NumPy buffers after each scan
                gc.collect()
            
            if result:
                clean_name = sorter.standardize_filename(result)
                new_name = f"{clean_name}{ext}"
                output_path = os.path.join(output_dir, new_name)
                
                counter = 1
                while os.path.exists(output_path):
                    new_name = f"{clean_name}_{counter}{ext}"
                    output_path = os.path.join(output_dir, new_name)
                    counter += 1
                
                with open(output_path, "wb") as f:
                    f.write(contents)
                
                return "processed", {
                    "original_name": filename,
                    "new_name": new_name,
                    "preview_url": f"/api/preview/{session_id}/{new_name}"
                }
            else:
                logger.debug("Scan failed for file")
                failed_path = os.path.join(failed_dir, safe_filename)
                
                counter = 1
                base_name, ext_part = os.path.splitext(safe_filename)
                while os.path.exists(failed_path):
                    failed_path = os.path.join(failed_dir, f"{base_name}_{counter}{ext_part}")
                    counter += 1
                
                with open(failed_path, "wb") as f:
                    f.write(contents)
                
                return "failed", {
                    "original_name": filename,
                    "preview_url": f"/api/preview-failed/{session_id}/{os.path.basename(failed_path)}"
                }
        except Exception as e:
            logger.error("Error processing file: %s", type(e).__name__)
            try:
                failed_path = os.path.join(failed_dir, safe_filename)
                counter = 1
                base_name, ext_part = os.path.splitext(safe_filename)
                while os.path.exists(failed_path):
                    failed_path = os.path.join(failed_dir, f"{base_name}_{counter}{ext_part}")
                    counter += 1
                with open(failed_path, "wb") as f:
                    f.write(contents)
                return "failed", {
                    "original_name": filename,
                    "preview_url": f"/api/preview-failed/{session_id}/{os.path.basename(failed_path)}"
                }
            except Exception:
                return "failed", {"original_name": filename}

    # Run all file processing tasks concurrently, bounded by the semaphore
    tasks = [_process_one(fd) for fd in validated_files]
    results = await asyncio.gather(*tasks)

    batch_elapsed = time.monotonic() - batch_start
    logger.info(
        "Batch processing complete: %d file(s) in %.2fs (concurrency=%d)",
        batch_size, batch_elapsed, BATCH_CONCURRENCY
    )

    for status, item in results:
        if status == "processed":
            processed.append(item)
        else:
            failed.append(item)
    
    # Create ZIP for processed files
    zip_path = os.path.join(temp_dir, "output.zip")
    output_files = os.listdir(output_dir)
    if output_files:
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for f in output_files:
                zf.write(os.path.join(output_dir, f), f)
    
    # Create ZIP for failed files
    failed_zip_path = os.path.join(temp_dir, "failed.zip")
    failed_files_list = os.listdir(failed_dir)
    if failed_files_list:
        with zipfile.ZipFile(failed_zip_path, 'w') as zf:
            for f in failed_files_list:
                zf.write(os.path.join(failed_dir, f), f)
    
    # Generate session token for authentication
    session_token = generate_session_token()
    token_hash = hashlib.sha256(session_token.encode()).hexdigest()
    
    temp_dirs[session_id] = {
        "path": temp_dir,
        "created_at": time.time(),
        "token_hash": token_hash,
        "download_count": 0,
        "access_count": 0
    }
    
    # Trigger cleanup of old sessions (older than 1 hour)
    current_time = time.time()
    expired = [sid for sid, data in temp_dirs.items() if current_time - data["created_at"] > 3600]
    for sid in expired:
        cleanup_session(sid)
    
    # Build response with appropriate download URLs
    response_data = {
        "session_id": session_id,
        "session_token": session_token,  # Client must store and send this
        "processed": processed,
        "failed": failed,
        "has_processed": len(processed) > 0,
        "has_failed": len(failed) > 0,
    }
    
    if output_files:
        response_data["download_url"] = f"/api/download/{session_id}"
    
    if failed_files_list:
        response_data["failed_download_url"] = f"/api/download-failed/{session_id}"
    
    return response_data

@app.get("/api/download/{session_id}")
async def download_zip(
    session_id: str,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    # Security: Validate session_id format to prevent path traversal
    validate_session_id(session_id)
    
    # Security: Validate session token
    session = validate_session_token(session_id, authorization)
    
    # Security: Limit downloads per session
    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Download limit exceeded")
    
    session["download_count"] += 1
    
    # Construct path safely
    base_path = Path(session["path"])
    zip_path = base_path / "output.zip"
    
    # Ensure resolved path is within base_path
    try:
        zip_path = zip_path.resolve()
        base_path_resolved = base_path.resolve()
        if not str(zip_path).startswith(str(base_path_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Zip file not found")
    
    return FileResponse(str(zip_path), filename="saree_organized.zip", media_type="application/zip")


@app.get("/api/download-failed/{session_id}")
async def download_failed_zip(
    session_id: str,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    # Security: Validate session_id format to prevent path traversal
    validate_session_id(session_id)
    
    # Security: Validate session token
    session = validate_session_token(session_id, authorization)
    
    # Security: Limit downloads per session
    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Download limit exceeded")
    
    session["download_count"] += 1
    
    # Construct path safely
    base_path = Path(session["path"])
    zip_path = base_path / "failed.zip"
    
    # Ensure resolved path is within base_path
    try:
        zip_path = zip_path.resolve()
        base_path_resolved = base_path.resolve()
        if not str(zip_path).startswith(str(base_path_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Failed images zip not found")
    
    return FileResponse(str(zip_path), filename="failed_images.zip", media_type="application/zip")


@app.get("/api/preview/{session_id}/{filename}")
async def get_preview(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    # Security: Validate session_id format to prevent path traversal
    validate_session_id(session_id)
    
    # Security: Validate and sanitize filename to prevent path traversal
    safe_filename = validate_filename(filename)
    
    # Security: Validate session token
    session = validate_session_token(session_id, authorization)
    
    # Security: Limit access count per session
    session["access_count"] += 1
    if session["access_count"] > 1000:  # Reasonable limit for previews
        raise HTTPException(status_code=429, detail="Too many requests")
    
    # Construct path safely using Path
    base_path = Path(session["path"]) / "output"
    file_path = base_path / safe_filename
    
    # Ensure resolved path is within base_path (critical security check)
    try:
        file_path = file_path.resolve()
        base_path_resolved = base_path.resolve()
        if not str(file_path).startswith(str(base_path_resolved)):
            logger.warning("Access denied for path: %s", file_path)
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception as e:
        logger.error("Path resolution error: %s", e)
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    if not file_path.exists():
        logger.error("Preview file not found: %s", file_path)
        # Debug: list directory
        try:
            logger.info("Dir contents of %s: %s", base_path, os.listdir(base_path))
        except Exception:
            pass
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(str(file_path))


@app.get("/api/preview-failed/{session_id}/{filename}")
async def get_failed_preview(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    # Security: Validate session_id format to prevent path traversal
    validate_session_id(session_id)
    
    # Security: Validate and sanitize filename to prevent path traversal
    safe_filename = validate_filename(filename)
    
    # Security: Validate session token
    session = validate_session_token(session_id, authorization)
    
    # Security: Limit access count per session
    session["access_count"] += 1
    if session["access_count"] > 1000:  # Reasonable limit for previews
        raise HTTPException(status_code=429, detail="Too many requests")
    
    # Construct path safely using Path - for failed folder
    base_path = Path(session["path"]) / "failed"
    file_path = base_path / safe_filename
    
    # Ensure resolved path is within base_path (critical security check)
    try:
        file_path = file_path.resolve()
        base_path_resolved = base_path.resolve()
        if not str(file_path).startswith(str(base_path_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(str(file_path))


@app.get("/api/download-single/{session_id}/{filename}")
async def download_single_image(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    # Security: Validate session_id format to prevent path traversal
    validate_session_id(session_id)
    
    # Security: Validate filename
    safe_filename = validate_filename(filename)
    
    # Security: Validate session token
    session = validate_session_token(session_id, authorization)
    
    # Security: Limit downloads per session
    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
        # Increase limit for single downloads specifically? 
        # Or Just bump the global limit significantly since individual downloads are chatty
        pass 
        # For now, sticking to the same counter but we might want to increase MAX_DOWNLOADS_PER_SESSION 
        # if users download many individual files.
        # Let's enforce it strictly for ZIPs, but maybe be lenient here or just bump the constant.
    
    session["access_count"] += 1 # Count as access rather than bulk download
    
    # Construct path safely
    base_path = Path(session["path"]) / "output"
    file_path = base_path / safe_filename
    
    # Ensure resolved path is within base_path
    try:
        file_path = file_path.resolve()
        base_path_resolved = base_path.resolve()
        if not str(file_path).startswith(str(base_path_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        str(file_path), 
        filename=safe_filename, 
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"}
    )


@app.get("/api/download-single-failed/{session_id}/{filename}")
async def download_single_failed_image(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    # Security: Validate session_id format
    validate_session_id(session_id)
    
    # Security: Validate filename
    safe_filename = validate_filename(filename)
    
    # Security: Validate session token
    session = validate_session_token(session_id, authorization)
    
    session["access_count"] += 1
    
    # Construct path safely
    base_path = Path(session["path"]) / "failed"
    file_path = base_path / safe_filename
    
    # Ensure resolved path is within base_path
    try:
        file_path = file_path.resolve()
        base_path_resolved = base_path.resolve()
        if not str(file_path).startswith(str(base_path_resolved)):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(
        str(file_path), 
        filename=safe_filename, 
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"}
    )


from pydantic import BaseModel

class RetryRequest(BaseModel):
    filenames: List[str]

@app.post("/api/retry/{session_id}")
async def retry_failed_images(
    session_id: str,
    request: RetryRequest,
    authorization: Optional[str] = Header(None, alias="Authorization")
):
    # Security Checks
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization)
    
    temp_dir = session["path"]
    failed_dir = os.path.join(temp_dir, "failed")
    output_dir = os.path.join(temp_dir, "output")
    
    if not os.path.exists(failed_dir):
        raise HTTPException(status_code=404, detail="No failed images found to retry")
    
    logger.info("Retrying %d files for session %s", len(request.filenames), session_id)
    
    retried_processed = []
    still_failed = []
    
    # Logic to process specific files
    files_to_retry = request.filenames
    if not files_to_retry:
         raise HTTPException(status_code=400, detail="No filenames provided")

    for filename in files_to_retry:
        try:
            safe_filename = validate_filename(filename)
            file_path = os.path.join(failed_dir, safe_filename)
            
            if not os.path.exists(file_path):
                logger.warning("File to retry not found: %s", safe_filename)
                continue
                
            # Read file content
            with open(file_path, "rb") as f:
                contents = f.read()
            
            img_ext = os.path.splitext(safe_filename)[1].lower()
            
            # Reprocess
            result = sorter.scan_barcode_from_bytes(contents)
            
            if result:
                # Success! Move to output
                clean_name = sorter.standardize_filename(result)
                new_name = f"{clean_name}{img_ext}"
                output_path = os.path.join(output_dir, new_name)
                
                # Handle duplicates in output
                counter = 1
                while os.path.exists(output_path):
                    new_name = f"{clean_name}_{counter}{img_ext}"
                    output_path = os.path.join(output_dir, new_name)
                    counter += 1
                
                # Write to output directory
                with open(output_path, "wb") as f_out:
                    f_out.write(contents)
                
                # Remove from failed directory logic? 
                # Yes, if successful, delete from failed.
                os.remove(file_path)
                
                retried_processed.append({
                    "original_name": safe_filename,
                    "new_name": new_name,
                    "preview_url": f"/api/preview/{session_id}/{new_name}"
                })
                logger.info("Retry success for %s -> %s", safe_filename, new_name)
            else:
                # Still failed, keep in failed directory
                still_failed.append(safe_filename)
                logger.debug("Retry failed for %s", safe_filename)
                
        except Exception as e:
            logger.error("Error retrying file %s: %s", filename, e)
            still_failed.append(filename)

    # Re-generate ZIPs if changes happened
    if retried_processed:
        # Re-zip processed
        zip_path = os.path.join(temp_dir, "output.zip")
        output_files = os.listdir(output_dir)
        if output_files:
            with zipfile.ZipFile(zip_path, 'w') as zf:
                for f in output_files:
                    zf.write(os.path.join(output_dir, f), f)
        
        # Re-zip failed (some might have been removed)
        failed_zip_path = os.path.join(temp_dir, "failed.zip")
        failed_files_list = os.listdir(failed_dir)
        if failed_files_list:
            with zipfile.ZipFile(failed_zip_path, 'w') as zf:
                for f in failed_files_list:
                    zf.write(os.path.join(failed_dir, f), f)
        else:
            # If no failed files left, remove the failed zip
            if os.path.exists(failed_zip_path):
                os.remove(failed_zip_path)

    return {
        "success": True,
        "retried_processed": retried_processed,
        "still_failed_count": len(os.listdir(failed_dir)),
        "download_url": f"/api/download/{session_id}" if os.listdir(output_dir) else None,
        "failed_download_url": f"/api/download-failed/{session_id}" if os.listdir(failed_dir) else None,
        "has_processed": len(os.listdir(output_dir)) > 0,
        "has_failed": len(os.listdir(failed_dir)) > 0
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
