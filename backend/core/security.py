from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import shutil
import time
from typing import Dict, Optional

from fastapi import HTTPException

logger = logging.getLogger("vr-saree-sorter.security")

# ---------------------------------------------------------------------------
# Session store
# In a real enterprise app this would be Redis/Memcached.
# Each entry shape:
#   {
#     "path": str,           # temp directory on disk
#     "token_hash": str,     # SHA-256 of the bearer token
#     "created_at": float,   # epoch seconds
#     "last_accessed": float,# epoch seconds (updated on every access)
#     "download_count": int,
#     "access_count": int,
#   }
# ---------------------------------------------------------------------------
temp_dirs: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Filename / session-ID validation
# ---------------------------------------------------------------------------

def validate_filename(filename: str) -> str:
    """Security: Prevent directory traversal and invalid characters."""
    safe_name = os.path.basename(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9.\-_ ()]', '_', safe_name)
    if not safe_name or safe_name.startswith('.'):
        safe_name = f"unnamed_file_{secrets.token_hex(4)}"
    return safe_name


def validate_session_id(session_id: str) -> None:
    """Security: Validate UUID format to prevent path traversal via session_id."""
    if not re.match(
        r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$',
        session_id,
    ):
        raise HTTPException(status_code=400, detail="Invalid session ID format")



def validate_session_token(session_id: str, auth_header: Optional[str]) -> dict:
    """Security: Prevent unauthorised downloading of ZIPs."""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication")

    token = auth_header.split(" ", 1)[1]
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    if session_id not in temp_dirs:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    session = temp_dirs[session_id]
    if session["token_hash"] != token_hash:
        raise HTTPException(status_code=403, detail="Invalid session token")

    # Touch last_accessed for TTL tracking
    session["last_accessed"] = time.time()
    return session


def generate_session_token() -> str:
    """Generate a secure random token for downloading session files."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Session lifecycle helpers
# ---------------------------------------------------------------------------

def create_session(temp_dir: str) -> tuple[str, str]:
    """
    Register a new session and return (session_id, session_token).
    The caller is responsible for creating the temp_dir on disk.
    """
    import uuid
    session_id = str(uuid.uuid4())
    token = generate_session_token()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    temp_dirs[session_id] = {
        "path": temp_dir,
        "token_hash": token_hash,
        "created_at": now,
        "last_accessed": now,
        "download_count": 0,
        "access_count": 0,
    }
    return session_id, token


def cleanup_session(session_id: str) -> None:
    """Remove a single session from the store and delete its temp directory."""
    session = temp_dirs.pop(session_id, None)
    if session:
        try:
            shutil.rmtree(session["path"], ignore_errors=True)
            logger.info("Cleaned up session %s", session_id)
        except Exception as exc:
            logger.error("Error cleaning up session %s: %s", session_id, exc)


def cleanup_expired_sessions(ttl_seconds: int) -> int:
    """
    Remove all sessions whose *last_accessed* time is older than ttl_seconds.
    Returns the number of sessions removed.
    """
    cutoff = time.time() - ttl_seconds
    expired = [
        sid for sid, data in list(temp_dirs.items())
        if data.get("last_accessed", data.get("created_at", 0)) < cutoff
    ]
    for sid in expired:
        cleanup_session(sid)
    return len(expired)


def cleanup_all_sessions() -> int:
    """Remove every active session (called on graceful shutdown)."""
    session_ids = list(temp_dirs.keys())
    for sid in session_ids:
        cleanup_session(sid)
    return len(session_ids)


def session_metrics() -> dict:
    """Return a lightweight snapshot of current session state."""
    return {
        "active_sessions": len(temp_dirs),
        "session_ids": list(temp_dirs.keys()),
    }
