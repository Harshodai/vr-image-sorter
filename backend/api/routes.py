from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging
import os
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

import core.metrics as metrics
from core.config import (
    ALLOWED_EXTENSIONS,
    BATCH_CONCURRENCY,
    ENABLE_METRICS,
    MAX_BATCH_SIZE,
    MAX_DOWNLOADS_PER_SESSION,
    MAX_FILE_SIZE,
    MAX_IMAGE_DIMENSION,
    MAX_TOTAL_SIZE,
    REQUEST_TIMEOUT,
)
from core.security import (
    create_session,
    temp_dirs,
    validate_filename,
    validate_session_id,
    validate_session_token,
)
from core.validation import (
    check_idempotency,
    compute_checksum,
    record_idempotency,
)
from scanner.engine_pool import ocr_pool
from scanner.pipeline import process_pipeline
from scanner.utils import standardize_filename
from api.models import RetryRequest

logger = logging.getLogger("vr-saree-sorter.api")
router = APIRouter()

# ---------------------------------------------------------------------------
# Concurrency controls
# ---------------------------------------------------------------------------
# Semaphore limits how many images are in-flight at once across all requests.
semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

# Bounded thread pool prevents thread explosion under high concurrency.
# Each thread runs one synchronous process_pipeline() call.
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=BATCH_CONCURRENCY,
    thread_name_prefix="ocr-worker",
)


# ---------------------------------------------------------------------------
# Core scan helper
# ---------------------------------------------------------------------------

async def scan_in_thread(contents: bytes) -> str | None:
    """
    Run process_pipeline() in the thread pool with a per-image timeout.
    Returns the VR code string or None on failure / timeout.
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, process_pipeline, contents),
            timeout=float(REQUEST_TIMEOUT),
        )
    except asyncio.TimeoutError:
        logger.error("Image processing timed out after %ds", REQUEST_TIMEOUT)
        metrics.increment("images_failed")
        return None


# ---------------------------------------------------------------------------
# Helper: unique output path (avoids overwriting duplicates)
# ---------------------------------------------------------------------------

def _unique_path(directory: str, name: str, ext: str) -> str:
    path = os.path.join(directory, f"{name}{ext}")
    counter = 1
    while os.path.exists(path):
        path = os.path.join(directory, f"{name}_{counter}{ext}")
        counter += 1
    return path


# ---------------------------------------------------------------------------
# POST /api/process
# ---------------------------------------------------------------------------

@router.post("/api/process")
async def process_images(
    files: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
):
    request_id = str(uuid.uuid4())[:8]
    metrics.increment("requests_total")

    # ── Input validation ────────────────────────────────────────────────
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_BATCH_SIZE} files allowed per request",
        )

    validated_files: list[dict] = []
    total_size = 0

    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type for '{file.filename}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
            )

        contents = await file.read()
        file_size = len(contents)
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File exceeds maximum size")

        total_size += file_size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(status_code=400, detail="Total upload size exceeds limit")

        # Image integrity check (PIL verify)
        try:
            img = Image.open(io.BytesIO(contents))
            width, height = img.size
            img.verify()
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                raise HTTPException(status_code=400, detail="Image dimensions exceed limit")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupted image")

        checksum = compute_checksum(contents)
        validated_files.append({
            "filename": file.filename,
            "contents": contents,
            "ext": ext,
            "checksum": checksum,
        })

    # ── Session setup ───────────────────────────────────────────────────
    is_new_session = False
    if session_id and session_id in temp_dirs:
        temp_dir = temp_dirs[session_id]["path"]
        output_dir = os.path.join(temp_dir, "output")
        failed_dir = os.path.join(temp_dir, "failed")
        session_token = None  # Frontend already holds it from chunk 1
    else:
        is_new_session = True
        temp_dir = tempfile.mkdtemp()
        output_dir = os.path.join(temp_dir, "output")
        failed_dir = os.path.join(temp_dir, "failed")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(failed_dir, exist_ok=True)
        session_id, session_token = create_session(temp_dir)

    processed: list[dict] = []
    failed: list[dict] = []

    batch_size = len(validated_files)
    logger.info(
        "[%s] Batch started: %d file(s), concurrency=%d",
        request_id, batch_size, BATCH_CONCURRENCY,
    )
    batch_start = time.monotonic()

    # ── Per-image processing coroutine ──────────────────────────────────
    async def _process_one(file_data: dict):
        contents = file_data["contents"]
        filename = file_data["filename"]
        ext = file_data["ext"]
        checksum = file_data["checksum"]
        safe_filename = validate_filename(filename or "unnamed")

        # Idempotency: serve from cache if this exact image was seen before
        cached, cached_result = check_idempotency(checksum)
        if cached:
            metrics.increment("idempotency_hits")
            logger.debug("[%s] Idempotency hit for %s", request_id, safe_filename)
            result = cached_result
        else:
            try:
                async with semaphore:
                    t0 = time.monotonic()
                    result = await scan_in_thread(contents)
                    elapsed = time.monotonic() - t0
                    metrics.record_processing_time(elapsed)
                    logger.info(
                        "[%s] Scanned %s in %.2fs → %s",
                        request_id, safe_filename, elapsed, result or "no match",
                    )
            except Exception as exc:
                logger.error(
                    "[%s] Unexpected error scanning %s: %s",
                    request_id, safe_filename, type(exc).__name__, exc_info=True,
                )
                result = None

            record_idempotency(checksum, result)

        if result:
            metrics.increment("images_processed")
            clean_name = standardize_filename(result)
            output_path = _unique_path(output_dir, clean_name, ext)
            new_name = os.path.basename(output_path)
            try:
                with open(output_path, "wb") as fh:
                    fh.write(contents)
            except OSError as exc:
                logger.error("[%s] Failed to write output file: %s", request_id, exc)
                metrics.increment("images_failed")
                return "failed", {"original_name": filename}
            return "processed", {
                "original_name": filename,
                "new_name": new_name,
                "preview_url": f"/api/preview/{session_id}/{new_name}",
            }
        else:
            metrics.increment("images_failed")
            failed_path = _unique_path(failed_dir, os.path.splitext(safe_filename)[0], ext)
            failed_name = os.path.basename(failed_path)
            try:
                with open(failed_path, "wb") as fh:
                    fh.write(contents)
            except OSError as exc:
                logger.error("[%s] Failed to write failed file: %s", request_id, exc)
                return "failed", {"original_name": filename}
            return "failed", {
                "original_name": filename,
                "preview_url": f"/api/preview-failed/{session_id}/{failed_name}",
            }

    # ── Gather all results concurrently ─────────────────────────────────
    results = await asyncio.gather(*[_process_one(fd) for fd in validated_files])

    batch_elapsed = time.monotonic() - batch_start
    logger.info(
        "[%s] Batch complete: %d file(s) in %.2fs",
        request_id, batch_size, batch_elapsed,
    )

    for status, item in results:
        if status == "processed":
            processed.append(item)
        else:
            failed.append(item)

    metrics.increment("requests_success")

    response_data: dict = {
        "session_id": session_id,
        "session_token": session_token,
        "processed": processed,
        "failed": failed,
        "has_processed": bool(processed),
        "has_failed": bool(failed),
    }
    if os.listdir(output_dir):
        response_data["download_url"] = f"/api/download/{session_id}"
    if os.listdir(failed_dir):
        response_data["failed_download_url"] = f"/api/download-failed/{session_id}"

    return response_data


# ---------------------------------------------------------------------------
# GET /api/download/{session_id}
# ---------------------------------------------------------------------------

@router.get("/api/download/{session_id}")
async def download_zip(
    session_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization)
    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Download limit exceeded")

    session["download_count"] += 1
    base_path = Path(session["path"])
    zip_path = (base_path / "output.zip").resolve()

    if not str(zip_path).startswith(str(base_path.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not zip_path.exists():
        output_dir = base_path / "output"
        if not output_dir.exists() or not any(output_dir.iterdir()):
            raise HTTPException(status_code=404, detail="No files to zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in output_dir.iterdir():
                zf.write(str(f), f.name)

    return FileResponse(str(zip_path), filename="saree_organized.zip", media_type="application/zip")


# ---------------------------------------------------------------------------
# GET /api/download-failed/{session_id}
# ---------------------------------------------------------------------------

@router.get("/api/download-failed/{session_id}")
async def download_failed_zip(
    session_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization)
    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Download limit exceeded")

    session["download_count"] += 1
    base_path = Path(session["path"])
    zip_path = (base_path / "failed.zip").resolve()

    if not str(zip_path).startswith(str(base_path.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not zip_path.exists():
        failed_dir = base_path / "failed"
        if not failed_dir.exists() or not any(failed_dir.iterdir()):
            raise HTTPException(status_code=404, detail="No failed files to zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in failed_dir.iterdir():
                zf.write(str(f), f.name)

    return FileResponse(str(zip_path), filename="failed_images.zip", media_type="application/zip")


# ---------------------------------------------------------------------------
# GET /api/preview/{session_id}/{filename}
# ---------------------------------------------------------------------------

@router.get("/api/preview/{session_id}/{filename}")
async def get_preview(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)

    session["access_count"] += 1
    if session["access_count"] > 1000:
        raise HTTPException(status_code=429, detail="Too many requests")

    base = (Path(session["path"]) / "output").resolve()
    file_path = (base / safe_filename).resolve()
    if not str(file_path).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))


# ---------------------------------------------------------------------------
# GET /api/preview-failed/{session_id}/{filename}
# ---------------------------------------------------------------------------

@router.get("/api/preview-failed/{session_id}/{filename}")
async def get_failed_preview(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)

    session["access_count"] += 1
    if session["access_count"] > 1000:
        raise HTTPException(status_code=429, detail="Too many requests")

    base = (Path(session["path"]) / "failed").resolve()
    file_path = (base / safe_filename).resolve()
    if not str(file_path).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Failed image not found")
    return FileResponse(str(file_path))


# ---------------------------------------------------------------------------
# GET /api/download-single/{session_id}/{filename}
# ---------------------------------------------------------------------------

@router.get("/api/download-single/{session_id}/{filename}")
async def download_single_image(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)
    session["access_count"] += 1

    base = (Path(session["path"]) / "output").resolve()
    file_path = (base / safe_filename).resolve()
    if not str(file_path).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        str(file_path),
        filename=safe_filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"},
    )


# ---------------------------------------------------------------------------
# GET /api/download-single-failed/{session_id}/{filename}
# ---------------------------------------------------------------------------

@router.get("/api/download-single-failed/{session_id}/{filename}")
async def download_single_failed_image(
    session_id: str,
    filename: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization)
    session["access_count"] += 1

    base = (Path(session["path"]) / "failed").resolve()
    file_path = (base / safe_filename).resolve()
    if not str(file_path).startswith(str(base)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        str(file_path),
        filename=safe_filename,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={safe_filename}"},
    )


# ---------------------------------------------------------------------------
# POST /api/retry/{session_id}
# ---------------------------------------------------------------------------

@router.post("/api/retry/{session_id}")
async def retry_failed_images(
    session_id: str,
    request: RetryRequest,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization)

    temp_dir = session["path"]
    failed_dir = os.path.join(temp_dir, "failed")
    output_dir = os.path.join(temp_dir, "output")

    if not os.path.exists(failed_dir):
        raise HTTPException(status_code=404, detail="No failed images found")

    files_to_retry = request.filenames
    if not files_to_retry:
        raise HTTPException(status_code=400, detail="No filenames provided")

    retried_processed: list[dict] = []

    for filename in files_to_retry:
        try:
            safe_filename = validate_filename(filename)
            file_path = os.path.join(failed_dir, safe_filename)
            if not os.path.exists(file_path):
                continue

            with open(file_path, "rb") as fh:
                contents = fh.read()
            img_ext = os.path.splitext(safe_filename)[1].lower()

            # Check idempotency cache before re-running the pipeline
            checksum = compute_checksum(contents)
            cached, cached_result = check_idempotency(checksum)
            result = cached_result if cached else await scan_in_thread(contents)
            if not cached:
                record_idempotency(checksum, result)

            if result:
                clean_name = standardize_filename(result)
                output_path = _unique_path(output_dir, clean_name, img_ext)
                new_name = os.path.basename(output_path)
                with open(output_path, "wb") as fh:
                    fh.write(contents)
                os.remove(file_path)
                metrics.increment("images_processed")
                retried_processed.append({
                    "original_name": safe_filename,
                    "new_name": new_name,
                    "preview_url": f"/api/preview/{session_id}/{new_name}",
                })
            else:
                metrics.increment("images_failed")
        except Exception as exc:
            logger.error("Error retrying file %s: %s", filename, exc)

    return {
        "success": True,
        "retried_processed": retried_processed,
        "still_failed_count": len(os.listdir(failed_dir)),
        "download_url": f"/api/download/{session_id}" if os.listdir(output_dir) else None,
        "failed_download_url": f"/api/download-failed/{session_id}" if os.listdir(failed_dir) else None,
        "has_processed": len(os.listdir(output_dir)) > 0,
        "has_failed": len(os.listdir(failed_dir)) > 0,
    }


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    pool_metrics = ocr_pool.metrics()
    return {
        "status": "ok",
        "ocr_pool": pool_metrics,
        "active_sessions": len(temp_dirs),
    }


# ---------------------------------------------------------------------------
# GET /metrics  (only when ENABLE_METRICS=true)
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def get_metrics():
    if not ENABLE_METRICS:
        raise HTTPException(status_code=404, detail="Metrics endpoint is disabled")
    return metrics.snapshot()
