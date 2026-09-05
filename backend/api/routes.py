from __future__ import annotations
import os
import re
import shutil
import io
import time
import uuid
import zipfile
import hashlib
import tempfile
import asyncio
import secrets
import threading
import concurrent.futures
import logging
from typing import List, Optional
from pathlib import Path
from PIL import Image

from fastapi import APIRouter, File, UploadFile, HTTPException, Header, BackgroundTasks, Request, Form
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from core.config import (
    MAX_BATCH_SIZE, ALLOWED_EXTENSIONS, MAX_FILE_SIZE, MAX_TOTAL_SIZE,
    MAX_IMAGE_DIMENSION, BATCH_CONCURRENCY, MAX_DOWNLOADS_PER_SESSION,
    MAX_ACCESS_COUNT_PER_SESSION, SESSION_TTL_SECONDS, SCAN_TIMEOUT_SECONDS,
    RETRY_SCAN_DIMENSION, SESSION_STORAGE_DIR
)
from core.security import (
    validate_filename, validate_session_id, validate_session_token,
    generate_session_token, save_session_metadata, restore_session_from_disk,
    temp_dirs
)
from scanner.utils import standardize_filename
from scanner.pipeline import process_pipeline
from scanner.result import ScanResult
from scanner.engine_pool import ocr_pool
from api.models import RetryRequest, ConfirmReviewRequest

logger = logging.getLogger("vr-saree-sorter.api")
router = APIRouter()

semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)
# Bounded thread pool prevents thread explosion under high concurrency
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_CONCURRENCY)

# ---------------------------------------------------------------------------
# Short-lived single-use download tokens
# ---------------------------------------------------------------------------
# Maps  token -> {"session_id": str, "expires_at": float}
# Tokens are single-use and expire after _DOWNLOAD_TOKEN_TTL_S seconds.
# They are issued via /api/issue-download-token/{session_id} and accepted
# ONLY on download routes — never on preview or process routes.
_download_tokens: dict[str, dict] = {}
_DOWNLOAD_TOKEN_TTL_S = 120  # 2 minutes; enough for any browser redirect

def _issue_download_token(session_id: str) -> str:
    """Create a short-lived, single-use download token for URL-based file downloads."""
    _purge_expired_download_tokens()
    token = secrets.token_urlsafe(32)
    _download_tokens[token] = {
        "session_id": session_id,
        "expires_at": time.monotonic() + _DOWNLOAD_TOKEN_TTL_S,
    }
    return token

def _peek_download_token(token: str, session_id: str) -> bool:
    """Validate a download token without consuming it. Returns True if valid."""
    _purge_expired_download_tokens()
    entry = _download_tokens.get(token)
    if not entry:
        return False
    if entry["session_id"] != session_id:
        return False
    if time.monotonic() > entry["expires_at"]:
        _download_tokens.pop(token, None)
        return False
    return True

def _consume_download_token(token: str, session_id: str) -> bool:
    """Validate and consume (delete) a download token. Returns True on success."""
    _purge_expired_download_tokens()
    entry = _download_tokens.pop(token, None)
    if not entry:
        return False
    if entry["session_id"] != session_id:
        return False
    if time.monotonic() > entry["expires_at"]:
        return False
    return True

def _purge_expired_download_tokens() -> None:
    now = time.monotonic()
    expired = [t for t, v in _download_tokens.items() if now > v["expires_at"]]
    for t in expired:
        _download_tokens.pop(t, None)

# ---------------------------------------------------------------------------
# Per-session synchronization locks
# ---------------------------------------------------------------------------
_session_locks: dict[str, threading.Lock] = {}
_session_locks_guard = threading.Lock()

def _get_session_lock(session_id: str) -> threading.Lock:
    """Retrieve or create a threading lock for serializing per-session critical sections."""
    with _session_locks_guard:
        lock = _session_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _session_locks[session_id] = lock
        return lock

# ---------------------------------------------------------------------------
# Session cleanup — rate-gated to avoid scanning all sessions on every request
# ---------------------------------------------------------------------------
_last_cleanup_time: float = 0.0
_CLEANUP_INTERVAL_S = 60.0  # run at most once per minute

def _maybe_cleanup_expired_sessions() -> None:
    global _last_cleanup_time
    now = time.time()
    if now - _last_cleanup_time < _CLEANUP_INTERVAL_S:
        return
    _last_cleanup_time = now
    expired = [sid for sid, data in list(temp_dirs.items())
               if now - data["created_at"] > SESSION_TTL_SECONDS]
    for sid in expired:
        cleanup_session(sid)

def cleanup_session(session_id: str):
    session = temp_dirs.pop(session_id, None)
    with _session_locks_guard:
        _session_locks.pop(session_id, None)
    if session:
        try:
            shutil.rmtree(session["path"], ignore_errors=True)
            logger.info("Cleaned up session %s", session_id)
        except Exception as e:
            logger.error("Error cleaning up session %s: %s", session_id, e)

async def scan_in_thread(contents: bytes, max_dim: int | None = None) -> ScanResult:
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_executor, process_pipeline, contents, max_dim),
            timeout=SCAN_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.error("Image processing timed out after %ss", SCAN_TIMEOUT_SECONDS)
        return ScanResult(method="none", reason="timed out")


def _unique_path(directory: str, name: str) -> tuple[str, str]:
    """Return (path, final_name), suffixing _1, _2... if the name is taken."""
    base, ext = os.path.splitext(name)
    candidate, counter = name, 1
    path = os.path.join(directory, candidate)
    while os.path.exists(path):
        candidate = f"{base}_{counter}{ext}"
        path = os.path.join(directory, candidate)
        counter += 1
    return path, candidate

def _is_zip_current(zip_path: Path, source_dir: Path) -> bool:
    """Verify whether existing archive is strictly newer than directory and all its files."""
    if not zip_path.exists() or not source_dir.exists():
        return False
    try:
        zip_mtime = zip_path.stat().st_mtime
        if source_dir.stat().st_mtime > zip_mtime:
            return False
        for f in source_dir.iterdir():
            if f.is_file() and f.stat().st_mtime > zip_mtime:
                return False
        return True
    except Exception:
        return False

def _invalidate_zips(base_path: Path) -> None:
    """Invalidate cached zip archives whenever source directory contents change."""
    try:
        (base_path / "output.zip").unlink(missing_ok=True)
    except Exception:
        pass
    try:
        (base_path / "failed.zip").unlink(missing_ok=True)
    except Exception:
        pass

def _build_zip_atomically(zip_path: Path, source_dir: Path) -> None:
    """Write zip to a temp file inside base_path then atomically publish via os.replace.
    Concurrent requests never read a partially-written archive.
    """
    tmp_path = zip_path.with_suffix(f".tmp.{secrets.token_hex(4)}")
    try:
        with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_STORED) as zf:
            for f in source_dir.iterdir():
                if f.is_file():
                    zf.write(str(f), f.name)
        os.replace(tmp_path, zip_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


@router.post("/api/process")
async def process_images(
    files: List[UploadFile] = File(...),
    session_id: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    token: Optional[str] = Form(None)
):
    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_BATCH_SIZE} files allowed per request")
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")

    is_new_session = False
    if session_id and isinstance(session_id, str):
        validate_session_id(session_id)
        # Require authentication before accessing or appending to an existing session
        auth = authorization if isinstance(authorization, str) else None
        session = validate_session_token(session_id, auth, allow_preview=False)
        temp_dir = session["path"]
        session_token = None  # Frontend already has token from initial session creation
    else:
        is_new_session = True
        session_id = str(uuid.uuid4())
        temp_dir = os.path.join(SESSION_STORAGE_DIR, session_id)
    output_dir = os.path.join(temp_dir, "output")
    failed_dir = os.path.join(temp_dir, "failed")
    review_dir = os.path.join(temp_dir, "review")
    for d in (output_dir, failed_dir, review_dir):
        os.makedirs(d, exist_ok=True)

    processed = []
    failed = []
    review = []

    # Validate files individually. A single bad file (wrong extension, over
    # the per-file size cap, corrupted/oversized image) used to raise an
    # HTTPException here, which aborted THIS ENTIRE REQUEST — up to
    # MAX_BATCH_SIZE files, or every image left in the chunk from the
    # frontend's perspective — with the good files in the same chunk silently
    # never processed at all (not even recorded as failed). One malformed
    # image could make a whole batch vanish. Each file is now judged on its
    # own: a rejection lands it in `failed` with a reason and the rest of the
    # chunk continues. MAX_TOTAL_SIZE remains a whole-request guard since it
    # protects server memory, not any single file's validity.
    validated_files = []
    total_size = 0

    for file in files:
        filename = file.filename or "unnamed_file"
        ext = os.path.splitext(filename)[1].lower() if filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            failed.append({
                "original_name": filename,
                "reason": f"unsupported file type '{ext or 'unknown'}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
            })
            continue

        contents = await file.read()
        file_size = len(contents)
        if file_size > MAX_FILE_SIZE:
            failed.append({
                "original_name": filename,
                "reason": f"file is {file_size // (1024*1024)}MB, exceeds the "
                          f"{MAX_FILE_SIZE // (1024*1024)}MB per-file limit",
            })
            continue

        total_size += file_size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(status_code=400, detail=f"Total upload size exceeds {MAX_TOTAL_SIZE // (1024*1024)}MB limit")

        try:
            with Image.open(io.BytesIO(contents)) as image:
                width, height = image.size
            if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                raise ValueError("dimensions exceed limit")
        except Exception:
            safe_filename = validate_filename(filename)
            failed_path, failed_name = _unique_path(failed_dir, safe_filename)
            try:
                with open(failed_path, "wb") as f:
                    f.write(contents)
                preview_url = f"/api/preview-failed/{session_id}/{failed_name}"
            except Exception:
                preview_url = None
            failed.append({
                "original_name": filename,
                "reason": "invalid, corrupted, or oversized image",
                "preview_url": preview_url,
            })
            continue

        validated_files.append({"filename": filename, "contents": contents, "ext": ext})

    batch_size = len(validated_files)
    logger.info("Batch processing started: %d file(s), concurrency limit=%d", batch_size, BATCH_CONCURRENCY)
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

            if result.is_confident:
                clean_name = standardize_filename(result.code)
                output_path, new_name = _unique_path(output_dir, f"{clean_name}{ext}")
                with open(output_path, "wb") as f:
                    f.write(contents)

                return "processed", {
                    "original_name": filename,
                    "new_name": new_name,
                    "confidence": round(result.confidence, 4),
                    "method": result.method,
                    "preview_url": f"/api/preview/{session_id}/{new_name}"
                }

            if result.code:
                # Something was read but it is not trustworthy enough to rename
                # with. Keep the ORIGINAL filename so nothing is renamed on a
                # guess, and surface the proposal for a human to confirm.
                review_path, review_name = _unique_path(review_dir, safe_filename)
                with open(review_path, "wb") as f:
                    f.write(contents)

                return "review", {
                    "original_name": filename,
                    "stored_name": review_name,
                    "suggested_name": f"{result.code}{ext}",
                    "suggested_code": result.code,
                    "confidence": round(result.confidence, 4),
                    "method": result.method,
                    "reason": result.reason,
                    "alternatives": [
                        {"code": c.code, "confidence": round(c.confidence, 4)}
                        for c in result.candidates[:5]
                    ],
                    "preview_url": f"/api/preview-review/{session_id}/{review_name}"
                }

            failed_path, failed_name = _unique_path(failed_dir, safe_filename)
            with open(failed_path, "wb") as f:
                f.write(contents)
            return "failed", {
                "original_name": filename,
                "reason": result.reason,
                "preview_url": f"/api/preview-failed/{session_id}/{failed_name}"
            }
        except Exception as e:
            logger.error("Error processing file: %s", type(e).__name__)
            try:
                failed_path, failed_name = _unique_path(failed_dir, safe_filename)
                with open(failed_path, "wb") as f:
                    f.write(contents)
                return "failed", {
                    "original_name": filename,
                    "reason": f"processing error: {type(e).__name__}",
                    "preview_url": f"/api/preview-failed/{session_id}/{failed_name}"
                }
            except Exception:
                return "failed", {"original_name": filename, "reason": "processing error"}

    tasks = [_process_one(fd) for fd in validated_files]
    results = await asyncio.gather(*tasks)

    batch_elapsed = time.monotonic() - batch_start
    logger.info("Batch processing complete: %d file(s) in %.2fs", batch_size, batch_elapsed)

    for status, item in results:
        if status == "processed": processed.append(item)
        elif status == "review": review.append(item)
        else: failed.append(item)

    # Invalidate cached zips whenever source directory contents change
    _invalidate_zips(Path(temp_dir))

    # Only create a new session entry for brand new sessions
    if is_new_session:
        session_token = generate_session_token()
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()
        session_data = {
            "path": temp_dir, "created_at": time.time(),
            "token_hash": token_hash, "download_count": 0, "access_count": 0
        }
        temp_dirs[session_id] = session_data
        await run_in_threadpool(save_session_metadata, session_id, session_data)
    else:
        session_token = None  # Frontend already has it from chunk 1
        if session_id in temp_dirs:
            await run_in_threadpool(save_session_metadata, session_id, temp_dirs[session_id])

    # Rate-gated session expiry — runs at most once per minute, not on every request
    await run_in_threadpool(_maybe_cleanup_expired_sessions)

    has_processed = os.path.isdir(output_dir) and any(
        f for f in os.listdir(output_dir) if not f.startswith(".")
    )
    has_failed = os.path.isdir(failed_dir) and any(
        f for f in os.listdir(failed_dir) if not f.startswith(".")
    )

    response_data = {
        "session_id": session_id,
        "session_token": session_token,
        "processed": processed,
        "failed": failed,
        "review": review,
        "has_processed": has_processed,
        "has_failed": has_failed,
        "has_review": len(review) > 0,
    }
    if has_processed:
        response_data["download_url"] = f"/api/download/{session_id}"
    if has_failed:
        response_data["failed_download_url"] = f"/api/download-failed/{session_id}"

    return response_data


@router.post("/api/issue-download-token/{session_id}")
async def issue_download_token(
    session_id: str,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Issue a short-lived (120s) single-use download token for URL-based file downloads.
    Requires header-based session authentication. The returned token may be appended
    to download URLs as ?dl_token=<token> for browser anchor downloads.
    """
    validate_session_id(session_id)
    validate_session_token(session_id, authorization, allow_preview=False)
    token = _issue_download_token(session_id)
    return {"download_token": token, "expires_in_seconds": _DOWNLOAD_TOKEN_TTL_S}


@router.get("/api/download/{session_id}")
async def download_zip(
    session_id: str,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    dl_token: Optional[str] = None,
):
    validate_session_id(session_id)

    # Accept either header-based auth or a single-use download token.
    # The dl_token is short-lived and single-use — it is NOT the session token.
    if dl_token:
        if not _peek_download_token(dl_token, session_id):
            raise HTTPException(status_code=403, detail="Invalid or expired download token")
        # Retrieve session without token verification (token already peeked above)
        from core.security import temp_dirs as _td
        session = _td.get(session_id)
        if not session:
            session = restore_session_from_disk(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
    else:
        session = validate_session_token(session_id, authorization, allow_preview=False)

    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Download limit exceeded")

    base_path = Path(session["path"])
    zip_path = base_path / "output.zip"
    output_dir = base_path / "output"

    try:
        zip_path = zip_path.resolve()
        if not str(zip_path).startswith(str(base_path.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not _is_zip_current(zip_path, output_dir):
        if not output_dir.exists() or not any(f for f in output_dir.iterdir() if f.is_file()):
            raise HTTPException(status_code=404, detail="No files to zip")
        await run_in_threadpool(_build_zip_atomically, zip_path, output_dir)

    with _get_session_lock(session_id):
        if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
            raise HTTPException(status_code=429, detail="Download limit exceeded")
        if dl_token:
            if not _consume_download_token(dl_token, session_id):
                raise HTTPException(status_code=403, detail="Invalid or expired download token")
        session["download_count"] += 1
        save_session_metadata(session_id, session)

    return FileResponse(str(zip_path), filename="saree_organized.zip", media_type="application/zip")


@router.get("/api/download-failed/{session_id}")
async def download_failed_zip(
    session_id: str,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    dl_token: Optional[str] = None,
):
    validate_session_id(session_id)

    if dl_token:
        if not _peek_download_token(dl_token, session_id):
            raise HTTPException(status_code=403, detail="Invalid or expired download token")
        from core.security import temp_dirs as _td
        session = _td.get(session_id)
        if not session:
            session = restore_session_from_disk(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
    else:
        session = validate_session_token(session_id, authorization, allow_preview=False)

    if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
        raise HTTPException(status_code=429, detail="Download limit exceeded")

    base_path = Path(session["path"])
    zip_path = base_path / "failed.zip"
    failed_dir = base_path / "failed"

    try:
        zip_path = zip_path.resolve()
        if not str(zip_path).startswith(str(base_path.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not _is_zip_current(zip_path, failed_dir):
        if not failed_dir.exists() or not any(f for f in failed_dir.iterdir() if f.is_file()):
            raise HTTPException(status_code=404, detail="No failed files to zip")
        await run_in_threadpool(_build_zip_atomically, zip_path, failed_dir)

    with _get_session_lock(session_id):
        if session["download_count"] >= MAX_DOWNLOADS_PER_SESSION:
            raise HTTPException(status_code=429, detail="Download limit exceeded")
        if dl_token:
            if not _consume_download_token(dl_token, session_id):
                raise HTTPException(status_code=403, detail="Invalid or expired download token")
        session["download_count"] += 1
        save_session_metadata(session_id, session)

    return FileResponse(str(zip_path), filename="failed_images.zip", media_type="application/zip")


@router.get("/api/preview/{session_id}/{filename}")
async def get_preview(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization"), token: Optional[str] = None):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization, query_token=token, allow_preview=True)

    session["access_count"] += 1
    if session["access_count"] > MAX_ACCESS_COUNT_PER_SESSION:
        raise HTTPException(status_code=429, detail="Too many requests")
    await run_in_threadpool(save_session_metadata, session_id, session)

    file_path = Path(session["path"]) / "output" / safe_filename

    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "output").resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))


@router.get("/api/preview-failed/{session_id}/{filename}")
async def get_failed_preview(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization"), token: Optional[str] = None):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization, query_token=token, allow_preview=True)

    session["access_count"] += 1
    if session["access_count"] > MAX_ACCESS_COUNT_PER_SESSION:
        raise HTTPException(status_code=429, detail="Too many requests")
    await run_in_threadpool(save_session_metadata, session_id, session)

    file_path = Path(session["path"]) / "failed" / safe_filename

    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "failed").resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Failed image not found")
    return FileResponse(str(file_path))


@router.get("/api/preview-review/{session_id}/{filename}")
async def get_review_preview(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization"), token: Optional[str] = None):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization, query_token=token, allow_preview=True)

    session["access_count"] += 1
    if session["access_count"] > MAX_ACCESS_COUNT_PER_SESSION:
        raise HTTPException(status_code=429, detail="Too many requests")
    await run_in_threadpool(save_session_metadata, session_id, session)

    file_path = Path(session["path"]) / "review" / safe_filename

    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "review").resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(file_path))


@router.post("/api/confirm-review/{session_id}")
async def confirm_review(session_id: str, request: ConfirmReviewRequest, authorization: Optional[str] = Header(None, alias="Authorization"), token: Optional[str] = None):
    """
    A human has read the label and is telling us the code. This is the only
    path by which a low-confidence image gets renamed, and the supplied code
    is trusted over anything the scanner proposed.
    """
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization, allow_preview=False)

    base = Path(session["path"])
    review_dir, output_dir = base / "review", base / "output"

    code = standardize_filename(request.code)
    if not re.fullmatch(r"VR\d{4,8}", code):
        raise HTTPException(status_code=400, detail="Code must look like VR followed by 4-8 digits")

    safe_filename = validate_filename(request.stored_name)
    src = (review_dir / safe_filename).resolve()
    if not str(src).startswith(str(review_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Image not found in review queue")

    ext = os.path.splitext(safe_filename)[1].lower()
    dest, new_name = _unique_path(str(output_dir), f"{code}{ext}")
    shutil.move(str(src), dest)
    _invalidate_zips(base)
    logger.info("Review confirmed by user: %s -> %s", safe_filename, new_name)

    remaining = len([f for f in os.listdir(review_dir) if not f.startswith(".")])
    return {
        "success": True,
        "new_name": new_name,
        "preview_url": f"/api/preview/{session_id}/{new_name}",
        "remaining_review": remaining,
    }


@router.get("/api/download-single/{session_id}/{filename}")
async def download_single_image(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization"), token: Optional[str] = None):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization, allow_preview=False)
    session["access_count"] += 1
    if session["access_count"] > MAX_ACCESS_COUNT_PER_SESSION:
        raise HTTPException(status_code=429, detail="Too many requests")
    await run_in_threadpool(save_session_metadata, session_id, session)

    file_path = Path(session["path"]) / "output" / safe_filename
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "output").resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path), filename=safe_filename, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={safe_filename}"})


@router.get("/api/download-single-failed/{session_id}/{filename}")
async def download_single_failed_image(session_id: str, filename: str, authorization: Optional[str] = Header(None, alias="Authorization"), token: Optional[str] = None):
    validate_session_id(session_id)
    safe_filename = validate_filename(filename)
    session = validate_session_token(session_id, authorization, allow_preview=False)
    session["access_count"] += 1
    if session["access_count"] > MAX_ACCESS_COUNT_PER_SESSION:
        raise HTTPException(status_code=429, detail="Too many requests")
    await run_in_threadpool(save_session_metadata, session_id, session)

    file_path = Path(session["path"]) / "failed" / safe_filename
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str((Path(session["path"]) / "failed").resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(file_path), filename=safe_filename, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={safe_filename}"})


@router.post("/api/retry/{session_id}")
async def retry_failed_images(session_id: str, request: RetryRequest, authorization: Optional[str] = Header(None, alias="Authorization"), token: Optional[str] = None):
    validate_session_id(session_id)
    session = validate_session_token(session_id, authorization, allow_preview=False)

    temp_dir = session["path"]
    failed_dir = os.path.join(temp_dir, "failed")
    output_dir = os.path.join(temp_dir, "output")

    if not os.path.exists(failed_dir):
        raise HTTPException(status_code=404, detail="No failed images found")

    review_dir = os.path.join(temp_dir, "review")
    os.makedirs(review_dir, exist_ok=True)

    retried_processed = []
    retried_review = []
    files_to_retry = request.filenames
    if not files_to_retry:
        raise HTTPException(status_code=400, detail="No filenames provided")

    still_failed_count = 0
    for filename in files_to_retry:
        try:
            safe_filename = validate_filename(filename)
            file_path = os.path.join(failed_dir, safe_filename)
            if not os.path.exists(file_path):
                continue

            with open(file_path, "rb") as f:
                contents = f.read()
            img_ext = os.path.splitext(safe_filename)[1].lower()

            # Escalate: re-scan at a higher resolution. Repeating the original
            # scan would re-run deterministic work and return the same answer.
            result = await scan_in_thread(contents, max_dim=RETRY_SCAN_DIMENSION)

            if result.is_confident:
                clean_name = standardize_filename(result.code)
                output_path, new_name = _unique_path(output_dir, f"{clean_name}{img_ext}")
                with open(output_path, "wb") as f_out:
                    f_out.write(contents)
                os.remove(file_path)

                retried_processed.append({
                    "original_name": safe_filename, "new_name": new_name,
                    "confidence": round(result.confidence, 4), "method": result.method,
                    "preview_url": f"/api/preview/{session_id}/{new_name}"
                })
            elif result.code:
                # Now readable but still not trustworthy: promote it out of the
                # failed pile into review rather than renaming on a guess.
                review_path, review_name = _unique_path(review_dir, safe_filename)
                with open(review_path, "wb") as f_out:
                    f_out.write(contents)
                os.remove(file_path)

                retried_review.append({
                    "original_name": safe_filename, "stored_name": review_name,
                    "suggested_code": result.code, "suggested_name": f"{result.code}{img_ext}",
                    "confidence": round(result.confidence, 4), "method": result.method,
                    "reason": result.reason,
                    "alternatives": [
                        {"code": c.code, "confidence": round(c.confidence, 4)}
                        for c in result.candidates[:5]
                    ],
                    "preview_url": f"/api/preview-review/{session_id}/{review_name}"
                })
            else:
                still_failed_count += 1
        except Exception as e:
            logger.error("Error retrying file %s: %s", filename, e)
            still_failed_count += 1

    _invalidate_zips(Path(temp_dir))

    has_output = os.path.isdir(output_dir) and any(
        f for f in os.listdir(output_dir) if not f.startswith(".")
    )
    has_failed = os.path.isdir(failed_dir) and any(
        f for f in os.listdir(failed_dir) if not f.startswith(".")
    )
    review_count = len([
        f for f in os.listdir(review_dir) if not f.startswith(".")
    ]) if os.path.isdir(review_dir) else 0

    return {
        "success": True,
        "retried_processed": retried_processed,
        "retried_review": retried_review,
        "still_failed_count": still_failed_count,
        "review_count": review_count,
        "download_url": f"/api/download/{session_id}" if has_output else None,
        "failed_download_url": f"/api/download-failed/{session_id}" if has_failed else None,
        "has_processed": has_output,
        "has_failed": has_failed,
    }


@router.get("/health")
async def health():
    return {"status": "ok", "model_loaded": ocr_pool._initialized}
