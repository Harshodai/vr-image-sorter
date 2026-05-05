from __future__ import annotations
import os
import io
import time
import uuid
import zipfile
import hashlib
import tempfile
import asyncio
import concurrent.futures
import logging
from typing import List, Optional
from pathlib import Path
from PIL import Image

from fastapi import APIRouter, File, UploadFile, HTTPException, Header, BackgroundTasks, Request, Form
from fastapi.responses import FileResponse, JSONResponse

from core.config import (
    MAX_BATCH_SIZE, ALLOWED_EXTENSIONS, MAX_FILE_SIZE, MAX_TOTAL_SIZE,
    MAX_IMAGE_DIMENSION, BATCH_CONCURRENCY, MAX_DOWNLOADS_PER_SESSION,
    WORKER_TIMEOUT,
)
from core.security import (
    validate_filename, validate_session_id, validate_session_token,
    generate_session_token, temp_dirs, session_manager,
)
from core.logger import new_correlation_id
from scanner.pipeline import process_pipeline
from scanner.engine_pool import ocr_pool
from api.models import RetryRequest

logger = logging.getLogger("vr-saree-sorter.api")
router = APIRouter()

semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)
# Bounded thread pool prevents thread explosion under high concurrency
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_CONCURRENCY)


def cleanup_session(session_id: str) -> None:
    """Delete a session's temp files via the SessionManager."""
    session_manager.delete(session_id)


async def scan_in_thread(contents: bytes) -> str | None:
    """Run the CPU-bound pipeline in the thread pool with a per-image timeout."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, process_pipeline, contents),
            timeout=float(WORKER_TIMEOUT),
        )
    except asyncio.TimeoutError:
        logger.error("Image processing timed out after %ds", WORKER_TIMEOUT)
        return None

@router.post("/api/process")
async def process_images(
    files: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
):
    # Assign a correlation ID for end-to-end tracing of this request
    cid = new_correlation_id()

    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Maximum {MAX_BATCH_SIZE} files allowed per request. "
                f"You submitted {len(files)}. "
                "Split your upload into smaller batches or increase MAX_BATCH_SIZE."
            ),
        )

    validated_files = []
    total_size = 0

    for file in files:
        ext = os.path.splitext(file.filename)[1].lower() if file.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type for '{file.filename}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
            )

        contents = await file.read()
        file_size = len(contents)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' exceeds the {MAX_FILE_SIZE // (1024*1024)}MB per-file limit",
            )

        total_size += file_size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Total upload size exceeds the {MAX_TOTAL_SIZE // (1024*1024)}MB batch limit",
            )

        try:
            image = Image.open(io.BytesIO(contents))
            width, height = image.size  # Read dimensions before verify
            image.verify()  # Validates integrity, invalidates object
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                raise HTTPException(status_code=400, detail="Image dimensions exceed limit")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail=f"Invalid or corrupted image: '{file.filename}'")

        validated_files.append({"filename": file.filename, "contents": contents, "ext": ext})

    is_new_session = False
    if session_id and session_id in session_manager:
        # Append to existing session
        temp_dir = session_manager[session_id]["path"]
        output_dir = os.path.join(temp_dir, "output")
        failed_dir = os.path.join(temp_dir, "failed")
        session_token = "existing_token"  # Frontend already holds the token from chunk 1
    else:
        is_new_session = True
        session_id = str(uuid.uuid4())
        temp_dir = tempfile.mkdtemp()
        output_dir = os.path.join(temp_dir, "output")
        failed_dir = os.path.join(temp_dir, "failed")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(failed_dir, exist_ok=True)

    processed = []
    failed = []

    batch_size = len(validated_files)
    logger.info(
        "Batch started: cid=%s files=%d concurrency=%d session=%s",
        cid, batch_size, BATCH_CONCURRENCY, session_id,
    )
    batch_start = time.monotonic()


    async def _process_one(file_data):
        contents = file_data["contents"]
        filename = file_data["filename"]
        ext = file_data["ext"]
        safe_filename = validate_filename(filename)
        
        try:
            async with semaphore:
                file_start = time.monotonic()
                result = await scan_in_thread(contents)
                elapsed = time.monotonic() - file_start
                logger.info("File scanned in %.2fs: %s", elapsed, safe_filename)
            
            if result:
                from scanner.utils import standardize_filename
                clean_name = standardize_filename(result)
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
                return "failed", {"original_name": filename, "preview_url": f"/api/preview-failed/{session_id}/{os.path.basename(failed_path)}"}
            except Exception:
                return "failed", {"original_name": filename}

    tasks = [_process_one(fd) for fd in validated_files]
    results = await asyncio.gather(*tasks)

    batch_elapsed = time.monotonic() - batch_start
    logger.info(
        "Batch complete: cid=%s files=%d processed=%d failed=%d elapsed=%.2fs",
        cid, batch_size, sum(1 for s, _ in results if s == "processed"),
        sum(1 for s, _ in results if s == "failed"), batch_elapsed,
    )

    for status, item in results:
        if status == "processed":
            processed.append(item)
        else:
            failed.append(item)

    # Removed eager zip generation here to prevent quadratic scaling on chunked uploads.
    # ZIPs will be generated dynamically upon download request.

    # Only create a new session entry for brand new sessions
    if is_new_session:
        session_token = generate_session_token()
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()
        session_manager.create(session_id, temp_dir, token_hash)
    else:
        # Reuse the existing token so the frontend's Authorization header stays valid
        session_token = None  # Frontend already has it from chunk 1

    # Periodic TTL-based cleanup (delegated to SessionManager)
    session_manager.cleanup_expired_sessions()
    
    response_data = {
        "session_id": session_id,
        "session_token": session_token,
        "processed": processed,
        "failed": failed,
        "has_processed": len(processed) > 0,
        "has_failed": len(failed) > 0,
    }
    if os.listdir(output_dir): response_data["download_url"] = f"/api/download/{session_id}"
    if os.listdir(failed_dir): response_data["failed_download_url"] = f"/api/download-failed/{session_id}"
    
    return response_data

@router.get("/api/download/{session_id}")
async def download_zip(session_id: str, background_tasks: BackgroundTasks, authorization: Optional[str] = Header(None, alias="Authorization")):
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization)
    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION: raise HTTPException(status_code=429, detail="Download limit exceeded")
    
    session["download_count"] += 1
    base_path = Path(session["path"])
    zip_path = base_path / "output.zip"
    
    try:
        zip_path = zip_path.resolve()
        if not str(zip_path).startswith(str(base_path.resolve())): raise HTTPException(status_code=403, detail="Access denied")
    except Exception: raise HTTPException(status_code=400, detail="Invalid path")
    
    if not zip_path.exists():
        # Generate zip dynamically
        output_dir = base_path / "output"
        if not output_dir.exists() or not any(output_dir.iterdir()):
            raise HTTPException(status_code=404, detail="No files to zip")
            
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for f in output_dir.iterdir():
                zf.write(str(f), f.name)
                
    return FileResponse(str(zip_path), filename="saree_organized.zip", media_type="application/zip")

@router.get("/api/download-failed/{session_id}")
async def download_failed_zip(session_id: str, background_tasks: BackgroundTasks, authorization: Optional[str] = Header(None, alias="Authorization")):
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization)
    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION: raise HTTPException(status_code=429, detail="Download limit exceeded")
    
    session["download_count"] += 1
    base_path = Path(session["path"])
    zip_path = base_path / "failed.zip"
    
    try:
        zip_path = zip_path.resolve()
        if not str(zip_path).startswith(str(base_path.resolve())): raise HTTPException(status_code=403, detail="Access denied")
    except Exception: raise HTTPException(status_code=400, detail="Invalid path")
    
    if not zip_path.exists():
        # Generate failed zip dynamically
        failed_dir = base_path / "failed"
        if not failed_dir.exists() or not any(failed_dir.iterdir()):
            raise HTTPException(status_code=404, detail="No failed files to zip")
            
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for f in failed_dir.iterdir():
                zf.write(str(f), f.name)
                
    return FileResponse(str(zip_path), filename="failed_images.zip", media_type="application/zip")

@router.get("/api/preview/{session_id}/{filename}")
async def get_preview(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization")):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)
    
    session["access_count"] += 1
    if session["access_count"] > 1000: raise HTTPException(status_code=429, detail="Too many requests")
    file_path = Path(session["path"]) / "output" / safe_filename
    
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "output").resolve())): raise HTTPException(status_code=403, detail="Access denied")
    except Exception: raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists(): raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))

@router.get("/api/preview-failed/{session_id}/{filename}")
async def get_failed_preview(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization")):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)
    
    session["access_count"] += 1
    if session["access_count"] > 1000: raise HTTPException(status_code=429, detail="Too many requests")
    file_path = Path(session["path"]) / "failed" / safe_filename
    
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "failed").resolve())): raise HTTPException(status_code=403, detail="Access denied")
    except Exception: raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists(): raise HTTPException(status_code=404, detail="Failed image not found")
    return FileResponse(str(file_path))

@router.get("/api/download-single/{session_id}/{filename}")
async def download_single_image(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization")):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)
    session["access_count"] += 1
    
    file_path = Path(session["path"]) / "output" / safe_filename
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "output").resolve())): raise HTTPException(status_code=403, detail="Access denied")
    except Exception: raise HTTPException(status_code=400, detail="Invalid file path")
    
    if not file_path.exists(): raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path), filename=safe_filename, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={safe_filename}"})

@router.get("/api/download-single-failed/{session_id}/{filename}")
async def download_single_failed_image(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization")):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)
    session["access_count"] += 1
    
    file_path = Path(session["path"]) / "failed" / safe_filename
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "failed").resolve())): raise HTTPException(status_code=403, detail="Access denied")
    except Exception: raise HTTPException(status_code=400, detail="Invalid file path")
    
    if not file_path.exists(): raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path), filename=safe_filename, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={safe_filename}"})

@router.post("/api/retry/{session_id}")
async def retry_failed_images(session_id: str, request: RetryRequest, authorization: Optional[str] = Header(None, alias="Authorization")):
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization)
    
    temp_dir = session["path"]
    failed_dir = os.path.join(temp_dir, "failed")
    output_dir = os.path.join(temp_dir, "output")
    
    if not os.path.exists(failed_dir): raise HTTPException(status_code=404, detail="No failed images found")
    
    retried_processed = []
    files_to_retry = request.filenames
    if not files_to_retry: raise HTTPException(status_code=400, detail="No filenames provided")

    for filename in files_to_retry:
        try:
            safe_filename = validate_filename(filename)
            file_path = os.path.join(failed_dir, safe_filename)
            if not os.path.exists(file_path): continue
                
            with open(file_path, "rb") as f: contents = f.read()
            img_ext = os.path.splitext(safe_filename)[1].lower()
            
            result = await scan_in_thread(contents)
            
            if result:
                from scanner.utils import standardize_filename
                clean_name = standardize_filename(result)
                new_name = f"{clean_name}{img_ext}"
                output_path = os.path.join(output_dir, new_name)
                
                counter = 1
                while os.path.exists(output_path):
                    new_name = f"{clean_name}_{counter}{img_ext}"
                    output_path = os.path.join(output_dir, new_name)
                    counter += 1
                
                with open(output_path, "wb") as f_out: f_out.write(contents)
                os.remove(file_path)
                
                retried_processed.append({
                    "original_name": safe_filename, "new_name": new_name,
                    "preview_url": f"/api/preview/{session_id}/{new_name}"
                })
        except Exception as e:
            logger.error("Error retrying file %s: %s", filename, e)

    if retried_processed:
        # Dynamic zip generation has been delegated to the download endpoints
        pass

    return {
        "success": True,
        "retried_processed": retried_processed,
        "still_failed_count": len(os.listdir(failed_dir)),
        "download_url": f"/api/download/{session_id}" if os.listdir(output_dir) else None,
        "failed_download_url": f"/api/download-failed/{session_id}" if os.listdir(failed_dir) else None,
        "has_processed": len(os.listdir(output_dir)) > 0,
        "has_failed": len(os.listdir(failed_dir)) > 0
    }

@router.get("/health")
async def health():
    """Health check endpoint — returns pool metrics, session stats, and resource health."""
    from core.monitoring import check_resource_health, get_memory_usage, get_cpu_usage
    from core.security import session_manager

    mem_pct, mem_gb = get_memory_usage()
    resource_health = check_resource_health()

    return {
        "status": "ok" if resource_health != "critical" else "degraded",
        "resource_health": resource_health,
        "memory_percent": mem_pct,
        "memory_gb": mem_gb,
        "cpu_percent": get_cpu_usage(),
        "ocr_pool": ocr_pool.health_check(),
        "sessions": session_manager.metrics(),
    }
