import re
import os
import secrets
import json
import hmac
import hashlib
import tempfile
import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException

logger = logging.getLogger("vr-saree-sorter.security")

# Global dictionary to store temporary session tracking in memory
# In a real enterprise app, this would be Redis/Memcached.
temp_dirs: Dict[str, Dict[str, Any]] = {}

SESSION_META_FILENAME = ".session_meta.json"

# Development mode is EXPLICITLY opt-in. An unset APP_ENV/ENVIRONMENT is
# treated as production so that misconfigured deployments fail loudly rather
# than silently using a weak dev secret.
APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "production")).lower()
IS_DEVELOPMENT = APP_ENV in ("development", "dev", "local", "test")

_configured_secret = os.environ.get("SESSION_SECRET_KEY")
if _configured_secret and len(_configured_secret.strip()) >= 16:
    SESSION_SECRET = _configured_secret.strip().encode("utf-8")
elif IS_DEVELOPMENT:
    if not _configured_secret:
        logger.warning("Using default development SESSION_SECRET_KEY. Configure SESSION_SECRET_KEY in production.")
        SESSION_SECRET = b"vr-image-sorter-session-secret-key-dev-only"
    else:
        SESSION_SECRET = _configured_secret.strip().encode("utf-8")
else:
    raise RuntimeError(
        "SESSION_SECRET_KEY environment variable (at least 16 high-entropy characters) "
        "is required in non-development deployments. "
        "Set APP_ENV=development to opt into the insecure dev default."
    )

# Trusted session base directories. tempfile.gettempdir() is intentionally
# excluded: it is world-writable on most OSes and must not be used as a
# restore source — an attacker-controlled session directory there could be
# used to inject arbitrary session metadata.
_TRUSTED_SESSION_BASES = [
    "temp_logs",
    "/app/temp_logs",
    "./temp_logs",
]

def compute_session_hmac(session_id: str, created_at: float, token_hash: Optional[str], download_count: int, access_count: int) -> str:
    """Compute HMAC-SHA256 signature for session metadata integrity protection."""
    payload = f"{session_id}:{created_at}:{token_hash or ''}:{download_count}:{access_count}"
    return hmac.new(SESSION_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()

def save_session_metadata(session_id: str, session: Optional[dict] = None) -> None:
    """Persist session metadata to disk with HMAC integrity protection."""
    if session is None:
        session = temp_dirs.get(session_id)
    if not session:
        return
    session_path = session.get("path")
    if not session_path or not os.path.exists(session_path):
        return

    created_at = float(session.get("created_at", 0.0))
    token_hash = session.get("token_hash")
    download_count = int(session.get("download_count", 0))
    access_count = int(session.get("access_count", 0))
    sig = compute_session_hmac(session_id, created_at, token_hash, download_count, access_count)

    meta = {
        "session_id": session_id,
        "created_at": created_at,
        "token_hash": token_hash,
        "download_count": download_count,
        "access_count": access_count,
        "signature": sig
    }

    meta_path = os.path.join(session_path, SESSION_META_FILENAME)
    try:
        temp_file = f"{meta_path}.tmp.{secrets.token_hex(4)}"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        os.replace(temp_file, meta_path)
    except Exception as e:
        logger.error("Failed to save session metadata for %s: %s", session_id, e)

def restore_session_from_disk(session_id: str) -> Optional[dict]:
    """Restore a session from disk verifying HMAC integrity protection and TTL expiration.
    Only searches trusted session base directories — world-writable paths like
    tempfile.gettempdir() are explicitly excluded to prevent session injection.
    """
    import time
    import shutil
    from core.config import SESSION_TTL_SECONDS

    for base in _TRUSTED_SESSION_BASES:
        for name in [session_id, f"session_{session_id}", f"vr_session_{session_id}"]:
            candidate_path = os.path.join(base, name)
            if os.path.exists(candidate_path) and os.path.isdir(candidate_path):
                meta_path = os.path.join(candidate_path, SESSION_META_FILENAME)
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)

                        meta_session_id = meta.get("session_id")
                        if meta_session_id != session_id:
                            logger.warning("Session ID mismatch in metadata: %s != %s", meta_session_id, session_id)
                            continue

                        created_at = float(meta.get("created_at", 0.0))
                        token_hash = meta.get("token_hash")
                        download_count = int(meta.get("download_count", 0))
                        access_count = int(meta.get("access_count", 0))
                        signature = meta.get("signature", "")

                        expected_sig = compute_session_hmac(session_id, created_at, token_hash, download_count, access_count)
                        if not hmac.compare_digest(signature, expected_sig):
                            logger.warning("HMAC signature mismatch for session %s on disk", session_id)
                            continue

                        # Check created_at against SESSION_TTL_SECONDS before restoring
                        if (time.time() - created_at) > SESSION_TTL_SECONDS:
                            logger.info("Session %s has expired (TTL=%ds); purging from disk", session_id, SESSION_TTL_SECONDS)
                            try:
                                shutil.rmtree(candidate_path, ignore_errors=True)
                            except Exception:
                                pass
                            continue

                        session = {
                            "path": candidate_path,
                            "created_at": created_at,
                            "token_hash": token_hash,
                            "download_count": download_count,
                            "access_count": access_count
                        }
                        temp_dirs[session_id] = session
                        return session
                    except Exception as e:
                        logger.error("Error reading session metadata for %s: %s", session_id, e)
                        continue
    return None

def validate_filename(filename: str) -> str:
    """Security: Prevent directory traversal and invalid characters"""
    safe_name = os.path.basename(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9.\-_ ()]', '_', safe_name)
    if not safe_name or safe_name.startswith('.'):
        safe_name = f"unnamed_file_{secrets.token_hex(4)}"
    return safe_name

def validate_session_id(session_id: str) -> None:
    """Security: Validate UUID format to prevent path traversal via session_id"""
    if not re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")

def validate_session_token(
    session_id: str,
    auth_header: Optional[str] = None,
    query_token: Optional[str] = None,
    allow_preview: bool = False
) -> dict:
    """Security: Prevent unauthorized downloading of zips and access to sessions.
    Resilient across server reloads and local single-user workflow.

    Preview policy:
    - If the session has a stored token_hash, a valid token is REQUIRED even for
      previews (token can be supplied via header or query param).
    - Tokenless preview access is only permitted when the session has no token_hash
      (e.g. freshly created sessions before the first chunk completes).
    """
    validate_session_id(session_id)

    # 1. Recover session from memory or disk
    session = temp_dirs.get(session_id)
    if not session:
        session = restore_session_from_disk(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    # 2. Extract token from header or query param
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif query_token:
        token = query_token.strip()

    stored_hash = session.get("token_hash")

    # 3. Authenticate token based on policy
    if not allow_preview:
        # Non-preview routes always require a valid token
        if not token:
            raise HTTPException(status_code=401, detail="Authentication token required")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if not stored_hash or not hmac.compare_digest(stored_hash, token_hash):
            raise HTTPException(status_code=403, detail="Invalid session token")
    else:
        # Preview routes: if the session has a token_hash, a valid token is required.
        # Only permit tokenless access when the session has no token_hash.
        if stored_hash:
            if not token:
                raise HTTPException(status_code=401, detail="Authentication token required for this session")
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            if not hmac.compare_digest(stored_hash, token_hash):
                raise HTTPException(status_code=403, detail="Invalid session token")

    return session

def generate_session_token() -> str:
    """Generate a secure random token for downloading session files"""
    return secrets.token_urlsafe(32)
