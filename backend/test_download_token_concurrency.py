"""
Regression Test: Concurrent Download Token Single-Use & Expiry

Verifies:
1. A single download token can only be consumed once, even under high concurrent race conditions.
2. Exactly 1 concurrent request succeeds (200), and all other concurrent requests are rejected (403).
3. Session download_count is incremented strictly once.
4. Expired tokens are rejected (403) before modifying session download_count.
5. Concurrent requests using two distinct tokens for one session enforce quota limit (only 1 succeeds, other rejected with 429).
"""
import os
import sys
import time
import tempfile
import asyncio
import secrets
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["APP_ENV"] = "development"

from fastapi import HTTPException, BackgroundTasks
from core.security import temp_dirs, save_session_metadata
from api.routes import (
    _issue_download_token,
    _consume_download_token,
    _download_tokens,
    download_zip,
    download_failed_zip,
)

import uuid

def setup_mock_session():
    """Create a temporary session on disk with a mock output file."""
    session_id = str(uuid.uuid4())
    base_dir = tempfile.mkdtemp(prefix=f"vr_test_{session_id}")
    output_dir = Path(base_dir) / "output"
    failed_dir = Path(base_dir) / "failed"
    output_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    # Write dummy file
    (output_dir / "VR123456.jpg").write_bytes(b"dummy image data")
    (failed_dir / "failed_01.jpg").write_bytes(b"dummy failed data")

    session_data = {
        "path": base_dir,
        "created_at": time.time(),
        "token_hash": "dummy_hash",
        "download_count": 0,
        "access_count": 0,
    }
    temp_dirs[session_id] = session_data
    save_session_metadata(session_id, session_data)
    return session_id, base_dir


def test_concurrent_token_consumption():
    """Verify that multiple concurrent consumers for the same token allow only 1 success."""
    print("\n[1/3] Testing atomic _consume_download_token with 20 concurrent threads...")
    session_id, _ = setup_mock_session()
    token = _issue_download_token(session_id)

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [
            executor.submit(_consume_download_token, token, session_id)
            for _ in range(20)
        ]
        for f in futures:
            results.append(f.result())

    success_count = sum(1 for r in results if r is True)
    fail_count = sum(1 for r in results if r is False)
    print(f"      Results: {success_count} True, {fail_count} False")
    assert success_count == 1, f"Expected exactly 1 success, got {success_count}"
    assert fail_count == 19, f"Expected exactly 19 rejections, got {fail_count}"
    print("      ✅ PASS: Exactly 1 concurrent consumer succeeded.")


def test_concurrent_download_endpoint():
    """Verify that concurrent download_zip route calls with a single token return 1 response and 403s."""
    print("\n[2/3] Testing download_zip endpoint under concurrent requests with 1 token...")
    session_id, base_dir = setup_mock_session()
    token = _issue_download_token(session_id)

    results = []
    errors = []

    async def call_download():
        bg = BackgroundTasks()
        try:
            resp = await download_zip(session_id=session_id, background_tasks=bg, dl_token=token)
            return ("SUCCESS", resp)
        except HTTPException as e:
            return ("HTTPException", e.status_code)
        except Exception as e:
            return ("ERROR", str(e))

    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(call_download())
        finally:
            loop.close()

    concurrency = 25
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(worker) for _ in range(concurrency)]
        for f in futures:
            res_type, val = f.result()
            if res_type == "SUCCESS":
                results.append(val)
            elif res_type == "HTTPException":
                errors.append(val)
            else:
                raise RuntimeError(f"Unexpected worker failure: {val}")

    session = temp_dirs.get(session_id)
    print(f"      Success responses: {len(results)}")
    print(f"      HTTP 403 rejections: {errors.count(403)} / {len(errors)}")
    print(f"      Session download_count: {session['download_count']}")

    assert len(results) == 1, f"Expected 1 successful FileResponse, got {len(results)}"
    assert errors.count(403) == concurrency - 1, f"Expected {concurrency - 1} 403 errors, got {errors.count(403)}"
    assert session["download_count"] == 1, f"Expected session download_count == 1, got {session['download_count']}"
    print("      ✅ PASS: Exactly 1 download served; all concurrent duplicates rejected with 403.")


def test_expired_token_rejected_before_count():
    """Verify that a token expired prior to / during download rejects before incrementing count."""
    print("\n[3/3] Testing expired token rejection prior to count increment...")
    session_id, base_dir = setup_mock_session()
    token = _issue_download_token(session_id)

    # Manually expire the token
    _download_tokens[token]["expires_at"] = time.monotonic() - 10

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        bg = BackgroundTasks()
        rejected = False
        try:
            loop.run_until_complete(download_zip(session_id=session_id, background_tasks=bg, dl_token=token))
        except HTTPException as e:
            if e.status_code == 403:
                rejected = True

        assert rejected, "Expected HTTPException(403) for expired token"
        session = temp_dirs.get(session_id)
        assert session["download_count"] == 0, f"Expected download_count == 0, got {session['download_count']}"
        print("      ✅ PASS: Expired token rejected with 403; download_count not incremented.")
    finally:
        loop.close()


def test_concurrent_two_tokens_quota_limit():
    """Verify that when a session has quota for only 1 remaining download,
    two concurrent requests using distinct valid tokens result in exactly
    1 success (200) and 1 rejection (429 Download limit exceeded), and the
    session download_count is strictly incremented once without exceeding the limit.
    """
    print("\n[4/4] Testing concurrent requests with two distinct tokens at quota limit...")
    from core.config import MAX_DOWNLOADS_PER_SESSION
    session_id, base_dir = setup_mock_session()

    # Configure session so exactly 1 download remains before hitting MAX_DOWNLOADS_PER_SESSION
    session_data = temp_dirs[session_id]
    session_data["download_count"] = MAX_DOWNLOADS_PER_SESSION - 1
    save_session_metadata(session_id, session_data)

    token1 = _issue_download_token(session_id)
    token2 = _issue_download_token(session_id)

    results = []
    errors = []

    async def call_download(tok: str):
        bg = BackgroundTasks()
        try:
            resp = await download_zip(session_id=session_id, background_tasks=bg, dl_token=tok)
            return ("SUCCESS", resp)
        except HTTPException as e:
            return ("HTTPException", e.status_code, e.detail)
        except Exception as e:
            return ("ERROR", str(e))

    def worker(tok: str):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(call_download(tok))
        finally:
            loop.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, t) for t in (token1, token2)]
        for f in futures:
            res = f.result()
            if res[0] == "SUCCESS":
                results.append(res[1])
            elif res[0] == "HTTPException":
                errors.append((res[1], res[2]))
            else:
                raise RuntimeError(f"Unexpected worker failure: {res[1]}")

    session = temp_dirs.get(session_id)
    print(f"      Success responses: {len(results)}")
    print(f"      HTTP errors: {errors}")
    print(f"      Session download_count: {session['download_count']}")

    assert len(results) == 1, f"Expected exactly 1 successful FileResponse, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 HTTPException, got {len(errors)}"
    status_code, detail = errors[0]
    assert status_code == 429, f"Expected 429 Download limit exceeded, got {status_code}"
    assert detail == "Download limit exceeded", f"Expected 'Download limit exceeded', got {detail}"
    assert session["download_count"] == MAX_DOWNLOADS_PER_SESSION, (
        f"Expected session download_count == {MAX_DOWNLOADS_PER_SESSION}, got {session['download_count']}"
    )
    print("      ✅ PASS: Exactly 1 permitted request succeeded; concurrent second token rejected with 429.")


def test_concurrent_two_tokens_failed_zip_quota_limit():
    """Verify that when a session has quota for only 1 remaining download,
    two concurrent requests to download_failed_zip using distinct valid tokens result in
    exactly 1 success (200) and 1 rejection (429 Download limit exceeded), and the
    session download_count is strictly incremented once.
    """
    print("\n[5/5] Testing concurrent requests with two distinct tokens on download-failed endpoint at quota limit...")
    from core.config import MAX_DOWNLOADS_PER_SESSION
    session_id, base_dir = setup_mock_session()

    session_data = temp_dirs[session_id]
    session_data["download_count"] = MAX_DOWNLOADS_PER_SESSION - 1
    save_session_metadata(session_id, session_data)

    token1 = _issue_download_token(session_id)
    token2 = _issue_download_token(session_id)

    results = []
    errors = []

    async def call_download(tok: str):
        bg = BackgroundTasks()
        try:
            resp = await download_failed_zip(session_id=session_id, background_tasks=bg, dl_token=tok)
            return ("SUCCESS", resp)
        except HTTPException as e:
            return ("HTTPException", e.status_code, e.detail)
        except Exception as e:
            return ("ERROR", str(e))

    def worker(tok: str):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(call_download(tok))
        finally:
            loop.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, t) for t in (token1, token2)]
        for f in futures:
            res = f.result()
            if res[0] == "SUCCESS":
                results.append(res[1])
            elif res[0] == "HTTPException":
                errors.append((res[1], res[2]))
            else:
                raise RuntimeError(f"Unexpected worker failure: {res[1]}")

    session = temp_dirs.get(session_id)
    print(f"      Success responses: {len(results)}")
    print(f"      HTTP errors: {errors}")
    print(f"      Session download_count: {session['download_count']}")

    assert len(results) == 1, f"Expected exactly 1 successful FileResponse, got {len(results)}"
    assert len(errors) == 1, f"Expected exactly 1 HTTPException, got {len(errors)}"
    status_code, detail = errors[0]
    assert status_code == 429, f"Expected 429 Download limit exceeded, got {status_code}"
    assert detail == "Download limit exceeded", f"Expected 'Download limit exceeded', got {detail}"
    assert session["download_count"] == MAX_DOWNLOADS_PER_SESSION, (
        f"Expected session download_count == {MAX_DOWNLOADS_PER_SESSION}, got {session['download_count']}"
    )
    print("      ✅ PASS: Exactly 1 permitted request succeeded; concurrent second token rejected with 429.")


def main():
    print("=" * 70)
    print("  RUNNING DOWNLOAD TOKEN CONCURRENCY REGRESSION SUITE")
    print("=" * 70)
    test_concurrent_token_consumption()
    test_concurrent_download_endpoint()
    test_expired_token_rejected_before_count()
    test_concurrent_two_tokens_quota_limit()
    test_concurrent_two_tokens_failed_zip_quota_limit()
    print("\n" + "=" * 70)
    print("  >>> ALL DOWNLOAD TOKEN CONCURRENCY TESTS PASSED! <<<")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
