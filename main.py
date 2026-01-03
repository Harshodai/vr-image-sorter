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

# Configure logging - server-side only, no sensitive details exposed
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Saree Organizer API")

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

# CORS: Use environment variable for allowed origins (security fix)
allowed_origins = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8080,http://localhost:5173,https://lovable.dev"
).split(",")

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

        return gray

    def decode_frame(self, image):
        barcodes = decode(image)
        for barcode in barcodes:
            barcode_data = barcode.data.decode("utf-8")
            if barcode_data:
                return barcode_data
        return None

    def scan_ocr(self, image):
        try:
            reader = self.get_reader()
            # Image is already a numpy array here
            
            # Preprocessing methods for OCR to handle noise/patterns
            methods = ["grayscale", "threshold_otsu", "original"]
            rotations = [0, 90, 180, 270]

            for method in methods:
                processed = self.preprocess_image(image, method)
                
                for angle in rotations:
                    # Rotate
                    if angle == 0:
                        img_to_scan = processed
                    elif angle == 90:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_CLOCKWISE)
                    elif angle == 180:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_180)
                    elif angle == 270:
                        img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    else:
                        img_to_scan = processed

                    # Scan
                    results = reader.readtext(img_to_scan)
                    for (bbox, text, prob) in results:
                        # Clean text
                        clean = text.replace(" ", "").upper()
                        # Strict matching for VR followed by digits
                        if "VR" in clean:
                            match = re.search(r"VR\d+", clean)
                            if match:
                                logger.debug("OCR match found")
                                return match.group(0)
        except Exception as e:
            logger.error("OCR processing error: %s", type(e).__name__)
        return None

    def scan_barcode_from_bytes(self, image_bytes) -> Optional[str]:
        """
        Attempts to scan a barcode from image bytes.
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

        # 1. Try Barcode Scan (Fast)
        methods = ["original", "grayscale", "sharpen", "threshold_otsu", "adaptive_threshold"]
        rotations = [0, 90, 180, 270]

        for method in methods:
            processed_img = self.preprocess_image(original_image, method)
            for angle in rotations:
                if angle == 0:
                    img_to_scan = processed_img
                else:
                    if angle == 90:
                        img_to_scan = cv2.rotate(processed_img, cv2.ROTATE_90_CLOCKWISE)
                    elif angle == 180:
                        img_to_scan = cv2.rotate(processed_img, cv2.ROTATE_180)
                    elif angle == 270:
                        img_to_scan = cv2.rotate(processed_img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                
                result = self.decode_frame(img_to_scan)
                if result:
                    logger.debug("Barcode match found")
                    return result
        
        # 2. Try OCR (Slow but fallback)
        logger.debug("Attempting OCR fallback")
        ocr_result = self.scan_ocr(original_image)
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
    
    logger.info("Processing batch of %d files", len(files))
    for file_data in validated_files:
        try:
            contents = file_data["contents"]
            filename = file_data["filename"]
            ext = file_data["ext"]
            
            result = sorter.scan_barcode_from_bytes(contents)
            
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
                
                processed.append({
                    "original_name": filename,
                    "new_name": new_name,
                    "preview_url": f"/api/preview/{session_id}/{new_name}"
                })
            else:
                logger.debug("Scan failed for file")
                # Save failed image to failed directory
                safe_filename = validate_filename(filename)
                failed_path = os.path.join(failed_dir, safe_filename)
                
                # Handle duplicate names in failed folder
                counter = 1
                base_name, ext_part = os.path.splitext(safe_filename)
                while os.path.exists(failed_path):
                    failed_path = os.path.join(failed_dir, f"{base_name}_{counter}{ext_part}")
                    counter += 1
                
                with open(failed_path, "wb") as f:
                    f.write(contents)
                
                failed.append({
                    "original_name": filename,
                    "preview_url": f"/api/preview-failed/{session_id}/{os.path.basename(failed_path)}"
                })
        except Exception as e:
            logger.error("Error processing file: %s", type(e).__name__)
            # Try to save failed file even if there was an error
            try:
                safe_filename = validate_filename(file_data["filename"])
                failed_path = os.path.join(failed_dir, safe_filename)
                counter = 1
                base_name, ext_part = os.path.splitext(safe_filename)
                while os.path.exists(failed_path):
                    failed_path = os.path.join(failed_dir, f"{base_name}_{counter}{ext_part}")
                    counter += 1
                with open(failed_path, "wb") as f:
                    f.write(file_data["contents"])
                failed.append({
                    "original_name": file_data["filename"],
                    "preview_url": f"/api/preview-failed/{session_id}/{os.path.basename(failed_path)}"
                })
            except Exception:
                failed.append({"original_name": file_data["filename"]})
    
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
