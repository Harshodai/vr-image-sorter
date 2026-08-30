import os
import sys
import time
import uuid
import io
import shutil
import tempfile
import hashlib
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from fastapi import HTTPException, UploadFile, BackgroundTasks

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["APP_ENV"] = "development"
os.environ["SESSION_SECRET_KEY"] = "vr-image-sorter-session-secret-key-dev-only"

import core.config as config
from core.security import temp_dirs, save_session_metadata, generate_session_token
import api.routes as routes
from api.routes import (
    download_single_image,
    download_single_failed_image,
    download_zip,
    download_failed_zip,
    process_images,
    _issue_download_token,
    _peek_download_token,
    _consume_download_token,
    _download_tokens,
)


def create_sample_image_bytes():
    buf = io.BytesIO()
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def run_tests():
    print("=== STARTING ROUTE FIXES TEST SUITE ===")
    
    # -----------------------------------------------------------------------
    # TEST 1: Issue 1 - MAX_ACCESS_COUNT_PER_SESSION on single-file downloads
    # -----------------------------------------------------------------------
    print("\n--- Test 1: Access count limiting on single-file downloads ---")
    test_session_id = str(uuid.uuid4())
    temp_dir = tempfile.mkdtemp()
    output_dir = os.path.join(temp_dir, "output")
    failed_dir = os.path.join(temp_dir, "failed")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(failed_dir, exist_ok=True)

    # Create dummy files
    img_bytes = create_sample_image_bytes()
    with open(os.path.join(output_dir, "VR12345.jpg"), "wb") as f:
        f.write(img_bytes)
    with open(os.path.join(failed_dir, "failed_01.jpg"), "wb") as f:
        f.write(img_bytes)

    session_token = generate_session_token()
    token_hash = hashlib.sha256(session_token.encode()).hexdigest()
    temp_dirs[test_session_id] = {
        "path": temp_dir,
        "created_at": time.time(),
        "token_hash": token_hash,
        "download_count": 0,
        "access_count": config.MAX_ACCESS_COUNT_PER_SESSION - 1,
    }
    save_session_metadata(test_session_id, temp_dirs[test_session_id])

    auth_header = f"Bearer {session_token}"

    # First request: access_count reaches MAX_ACCESS_COUNT_PER_SESSION (allowed)
    res = await download_single_image(test_session_id, "VR12345.jpg", authorization=auth_header)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert temp_dirs[test_session_id]["access_count"] == config.MAX_ACCESS_COUNT_PER_SESSION

    # Second request: access_count exceeds limit -> 429
    try:
        await download_single_image(test_session_id, "VR12345.jpg", authorization=auth_header)
        assert False, "Expected 429 HTTPException for download_single_image"
    except HTTPException as e:
        assert e.status_code == 429, f"Expected 429, got {e.status_code}"
        assert e.detail == "Too many requests"
        print("  ✓ download_single_image raised 429 on exceeding access limit")

    # Reset access count for failed image test
    temp_dirs[test_session_id]["access_count"] = config.MAX_ACCESS_COUNT_PER_SESSION - 1
    save_session_metadata(test_session_id, temp_dirs[test_session_id])

    # First request for failed image: allowed
    res = await download_single_failed_image(test_session_id, "failed_01.jpg", authorization=auth_header)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert temp_dirs[test_session_id]["access_count"] == config.MAX_ACCESS_COUNT_PER_SESSION

    # Second request: exceeds limit -> 429
    try:
        await download_single_failed_image(test_session_id, "failed_01.jpg", authorization=auth_header)
        assert False, "Expected 429 HTTPException for download_single_failed_image"
    except HTTPException as e:
        assert e.status_code == 429, f"Expected 429, got {e.status_code}"
        assert e.detail == "Too many requests"
        print("  ✓ download_single_failed_image raised 429 on exceeding access limit")

    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dirs.pop(test_session_id, None)

    # -----------------------------------------------------------------------
    # TEST 2: Issue 2 - Comment check in process_images
    # -----------------------------------------------------------------------
    print("\n--- Test 2: Comment in process_images bounded by MAX_TOTAL_SIZE ---")
    routes_path = Path(__file__).resolve().parent.parent / "api" / "routes.py"
    with open(routes_path, "r", encoding="utf-8") as f:
        routes_content = f.read()
    assert "MAX_TOTAL_SIZE rather than MAX_FILE_SIZE" in routes_content, "Comment update missing in routes.py"
    print("  ✓ Comment accurately documents peak memory bounding by MAX_TOTAL_SIZE")

    # -----------------------------------------------------------------------
    # TEST 3: Issue 5 - Early auth & session validation in process_images
    # -----------------------------------------------------------------------
    print("\n--- Test 3: Early session and auth validation on /api/process ---")
    bad_session_id = "not-a-valid-uuid"
    upload_file = UploadFile(filename="test.jpg", file=io.BytesIO(img_bytes))

    # Invalid session UUID format
    try:
        await process_images(files=[upload_file], session_id=bad_session_id)
        assert False, "Expected 400 for invalid session_id"
    except HTTPException as e:
        assert e.status_code == 400, f"Expected 400, got {e.status_code}"
        print("  ✓ Invalid session_id rejected immediately with 400")

    # Non-existent session
    valid_uuid_missing = str(uuid.uuid4())
    upload_file = UploadFile(filename="test.jpg", file=io.BytesIO(img_bytes))
    try:
        await process_images(files=[upload_file], session_id=valid_uuid_missing, authorization="Bearer dummy")
        assert False, "Expected 404 for missing session"
    except HTTPException as e:
        assert e.status_code == 404, f"Expected 404, got {e.status_code}"
        print("  ✓ Missing session rejected immediately with 404")

    # Existing session with invalid auth token (verify files are not read!)
    existing_session_id = str(uuid.uuid4())
    temp_dir2 = tempfile.mkdtemp()
    os.makedirs(os.path.join(temp_dir2, "output"), exist_ok=True)
    real_token = generate_session_token()
    temp_dirs[existing_session_id] = {
        "path": temp_dir2,
        "created_at": time.time(),
        "token_hash": hashlib.sha256(real_token.encode()).hexdigest(),
        "download_count": 0,
        "access_count": 0,
    }
    save_session_metadata(existing_session_id, temp_dirs[existing_session_id])

    # Unauthenticated / wrong token call
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = "test.jpg"
    mock_file.read = MagicMock()

    try:
        await process_images(files=[mock_file], session_id=existing_session_id, authorization="Bearer wrong-token")
        assert False, "Expected 403 for wrong token"
    except HTTPException as e:
        assert e.status_code == 403, f"Expected 403, got {e.status_code}"
        assert not mock_file.read.called, "File should NOT have been read before auth validation!"
        print("  ✓ Existing session with invalid token rejected with 403 BEFORE reading upload bytes")

    shutil.rmtree(temp_dir2, ignore_errors=True)
    temp_dirs.pop(existing_session_id, None)

    # -----------------------------------------------------------------------
    # TEST 4: Issue 3 - has_processed / has_failed derived from directories
    # -----------------------------------------------------------------------
    print("\n--- Test 4: Persisted directory check for has_processed / has_failed ---")
    session_id_persist = str(uuid.uuid4())
    temp_dir3 = tempfile.mkdtemp()
    out_dir = os.path.join(temp_dir3, "output")
    fail_dir = os.path.join(temp_dir3, "failed")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(fail_dir, exist_ok=True)

    # Put an existing file in output/ from a previous chunk
    with open(os.path.join(out_dir, "VR99999.jpg"), "wb") as f:
        f.write(img_bytes)

    persist_token = generate_session_token()
    temp_dirs[session_id_persist] = {
        "path": temp_dir3,
        "created_at": time.time(),
        "token_hash": hashlib.sha256(persist_token.encode()).hexdigest(),
        "download_count": 0,
        "access_count": 0,
    }
    save_session_metadata(session_id_persist, temp_dirs[session_id_persist])

    # Mock scan_in_thread so current chunk only produces a review or failed result (processed is empty)
    with patch("api.routes.scan_in_thread") as mock_scan:
        from scanner.result import ScanResult
        # Scan returns unconfident / failed
        mock_scan.return_value = ScanResult(method="none", reason="unreadable", confidence=0.0)

        upload_file2 = UploadFile(filename="fail.jpg", file=io.BytesIO(img_bytes))
        resp = await process_images(
            files=[upload_file2],
            session_id=session_id_persist,
            authorization=f"Bearer {persist_token}"
        )

        assert resp["has_processed"] is True, "has_processed should be True because output/ directory has files"
        assert resp["has_failed"] is True, "has_failed should be True because failed/ directory has files"
        assert resp["download_url"] == f"/api/download/{session_id_persist}"
        assert resp["failed_download_url"] == f"/api/download-failed/{session_id_persist}"
        assert len(resp["processed"]) == 0, "Current chunk processed list should be empty"
        assert len(resp["failed"]) == 1, "Current chunk failed list should have 1 item"
        print("  ✓ has_processed and has_failed accurately reflect directory contents across chunks")

    shutil.rmtree(temp_dir3, ignore_errors=True)
    temp_dirs.pop(session_id_persist, None)

    # -----------------------------------------------------------------------
    # TEST 5: Issue 4 - _maybe_cleanup_expired_sessions uses run_in_threadpool
    # -----------------------------------------------------------------------
    print("\n--- Test 5: Cleanup execution via run_in_threadpool ---")
    with patch("api.routes.run_in_threadpool", wraps=routes.run_in_threadpool) as mock_rit:
        upload_file3 = UploadFile(filename="clean_test.jpg", file=io.BytesIO(img_bytes))
        with patch("api.routes.scan_in_thread") as mock_scan:
            mock_scan.return_value = ScanResult(method="ocr", code="VR55555", confidence=0.99)
            resp = await process_images(files=[upload_file3])
            
            # Verify run_in_threadpool was called with _maybe_cleanup_expired_sessions
            calls = [call_args[0][0] for call_args in mock_rit.call_args_list]
            assert routes._maybe_cleanup_expired_sessions in calls, "_maybe_cleanup_expired_sessions should be dispatched via run_in_threadpool"
            print("  ✓ _maybe_cleanup_expired_sessions is dispatched via run_in_threadpool")

            # Cleanup newly created session
            new_sid = resp["session_id"]
            if new_sid in temp_dirs:
                shutil.rmtree(temp_dirs[new_sid]["path"], ignore_errors=True)
                temp_dirs.pop(new_sid, None)

    # -----------------------------------------------------------------------
    # TEST 6: Issue 6 - Non-destructive token peek until archive ready
    # -----------------------------------------------------------------------
    print("\n--- Test 6: Non-destructive dl_token peek until archive ready ---")
    dl_session_id = str(uuid.uuid4())
    temp_dir4 = tempfile.mkdtemp()
    dl_out_dir = os.path.join(temp_dir4, "output")
    dl_fail_dir = os.path.join(temp_dir4, "failed")
    os.makedirs(dl_out_dir, exist_ok=True)
    os.makedirs(dl_fail_dir, exist_ok=True)

    session_tok = generate_session_token()
    temp_dirs[dl_session_id] = {
        "path": temp_dir4,
        "created_at": time.time(),
        "token_hash": hashlib.sha256(session_tok.encode()).hexdigest(),
        "download_count": 0,
        "access_count": 0,
    }
    save_session_metadata(dl_session_id, temp_dirs[dl_session_id])

    bg_tasks = BackgroundTasks()

    # Case A: dl_token for session with EMPTY output dir (should 404, but token must NOT be consumed)
    token_a = _issue_download_token(dl_session_id)
    assert _peek_download_token(token_a, dl_session_id) is True

    try:
        await download_zip(dl_session_id, background_tasks=bg_tasks, dl_token=token_a)
        assert False, "Expected 404 No files to zip"
    except HTTPException as e:
        assert e.status_code == 404, f"Expected 404, got {e.status_code}"
        # Token must STILL be valid because archive wasn't ready!
        assert _peek_download_token(token_a, dl_session_id) is True, "Token must NOT be consumed on 404 failure!"
        assert temp_dirs[dl_session_id]["download_count"] == 0, "download_count must not increment on failure"
        print("  ✓ dl_token preserved and download_count untouched on missing archive (404)")

    # Case B: Exceeded download limit (should 429, token must NOT be consumed)
    temp_dirs[dl_session_id]["download_count"] = config.MAX_DOWNLOADS_PER_SESSION
    save_session_metadata(dl_session_id, temp_dirs[dl_session_id])

    try:
        await download_zip(dl_session_id, background_tasks=bg_tasks, dl_token=token_a)
        assert False, "Expected 429 Download limit exceeded"
    except HTTPException as e:
        assert e.status_code == 429, f"Expected 429, got {e.status_code}"
        assert _peek_download_token(token_a, dl_session_id) is True, "Token must NOT be consumed on 429 failure!"
        print("  ✓ dl_token preserved on download limit exceeded (429)")

    # Case C: Populate output dir, reset download_count, and perform successful download
    temp_dirs[dl_session_id]["download_count"] = 0
    save_session_metadata(dl_session_id, temp_dirs[dl_session_id])
    with open(os.path.join(dl_out_dir, "VR11111.jpg"), "wb") as f:
        f.write(img_bytes)

    res_zip = await download_zip(dl_session_id, background_tasks=bg_tasks, dl_token=token_a)
    assert res_zip.status_code == 200, f"Expected 200, got {res_zip.status_code}"
    # Token MUST NOW BE CONSUMED!
    assert _peek_download_token(token_a, dl_session_id) is False, "Token MUST be consumed after successful download!"
    assert temp_dirs[dl_session_id]["download_count"] == 1, "download_count must be 1"
    print("  ✓ dl_token consumed and download_count incremented on successful download_zip")

    # Case D: Test same behavior on download_failed_zip
    token_b = _issue_download_token(dl_session_id)
    # Empty failed dir -> 404, token preserved
    try:
        await download_failed_zip(dl_session_id, background_tasks=bg_tasks, dl_token=token_b)
        assert False, "Expected 404 No failed files to zip"
    except HTTPException as e:
        assert e.status_code == 404, f"Expected 404, got {e.status_code}"
        assert _peek_download_token(token_b, dl_session_id) is True, "Token must NOT be consumed on 404 failed zip"
        print("  ✓ dl_token preserved on empty failed archive (404)")

    # Populate failed dir and download
    with open(os.path.join(dl_fail_dir, "failed_image.jpg"), "wb") as f:
        f.write(img_bytes)

    res_fail_zip = await download_failed_zip(dl_session_id, background_tasks=bg_tasks, dl_token=token_b)
    assert res_fail_zip.status_code == 200, f"Expected 200, got {res_fail_zip.status_code}"
    assert _peek_download_token(token_b, dl_session_id) is False, "Token MUST be consumed after successful download_failed_zip!"
    assert temp_dirs[dl_session_id]["download_count"] == 2, "download_count must be 2"
    print("  ✓ dl_token consumed and download_count incremented on successful download_failed_zip")

    # Case E: Invalid or expired token rejection
    try:
        await download_zip(dl_session_id, background_tasks=bg_tasks, dl_token="non-existent-token")
        assert False, "Expected 403 for non-existent token"
    except HTTPException as e:
        assert e.status_code == 403, f"Expected 403, got {e.status_code}"
        print("  ✓ Non-existent dl_token rejected with 403")

    shutil.rmtree(temp_dir4, ignore_errors=True)
    temp_dirs.pop(dl_session_id, None)

    print("\n=== ALL ROUTE FIX TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(run_tests())
