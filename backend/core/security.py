"""
core/security.py
~~~~~~~~~~~~~~~~
Authentication helpers and the central ``SessionManager`` that tracks every
live upload session.

``SessionManager`` replaces the old bare ``temp_dirs`` dict and adds:
- TTL-based expiration (SESSION_TTL from config)
- Hard cap on concurrent sessions (MAX_CONCURRENT_SESSIONS)
- Per-session state tracking (created_at, last_accessed_at, status)
- Aggregate metrics (total_sessions, active_sessions, cleanup_count)
- Structured logging for every lifecycle event

The module-level ``temp_dirs`` alias is kept so that existing call-sites in
routes.py continue to work without modification.
"""

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
# SessionManager
# ---------------------------------------------------------------------------

class SessionManager:
    """In-process session store with TTL expiration and resource limits.

    Each session entry is a plain dict with the following keys:
        path             - absolute path to the temp directory
        token_hash       - SHA-256 hex digest of the bearer token
        created_at       - Unix timestamp when the session was created
        last_accessed_at - Unix timestamp of the most recent access
        status           - "active" | "expired" | "cleaned"
        download_count   - number of ZIP downloads served
        access_count     - number of preview/single-file requests served
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, dict] = {}
        # Metrics
        self.total_sessions: int = 0
        self.cleanup_count: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active_sessions(self) -> int:
        return sum(1 for s in self._sessions.values() if s["status"] == "active")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(self, session_id: str, path: str, token_hash: str) -> dict:
        """Register a new session.  Raises ``HTTPException(503)`` when the
        session cap (MAX_CONCURRENT_SESSIONS) would be exceeded."""
        # Import here to avoid circular imports at module load time
        from core.config import MAX_CONCURRENT_SESSIONS

        if self.active_sessions >= MAX_CONCURRENT_SESSIONS:
            logger.warning(
                "Session cap reached (%d/%d); rejecting new session %s",
                self.active_sessions, MAX_CONCURRENT_SESSIONS, session_id,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Server is at capacity ({MAX_CONCURRENT_SESSIONS} concurrent sessions). "
                    "Please try again later."
                ),
            )

        now = time.time()
        entry = {
            "path": path,
            "token_hash": token_hash,
            "created_at": now,
            "last_accessed_at": now,
            "status": "active",
            "download_count": 0,
            "access_count": 0,
        }
        self._sessions[session_id] = entry
        self.total_sessions += 1
        logger.info(
            "Session created: %s | active=%d total=%d",
            session_id, self.active_sessions, self.total_sessions,
        )
        return entry

    def get(self, session_id: str) -> Optional[dict]:
        """Return the session dict and update ``last_accessed_at``, or None."""
        entry = self._sessions.get(session_id)
        if entry and entry["status"] == "active":
            entry["last_accessed_at"] = time.time()
            return entry
        return None

    def __contains__(self, session_id: str) -> bool:
        entry = self._sessions.get(session_id)
        return entry is not None and entry["status"] == "active"

    def __getitem__(self, session_id: str) -> dict:
        entry = self._sessions.get(session_id)
        if entry is None:
            raise KeyError(session_id)
        return entry

    def __setitem__(self, session_id: str, value: dict) -> None:
        self._sessions[session_id] = value

    def pop(self, session_id: str, default=None):
        """Remove and return a session entry (used by cleanup_session)."""
        return self._sessions.pop(session_id, default)

    def items(self):
        return self._sessions.items()

    def keys(self):
        return self._sessions.keys()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def delete(self, session_id: str) -> bool:
        """Delete a session's temp files and remove it from the store.

        Returns True if the session existed and was cleaned, False otherwise.
        """
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return False

        path = entry.get("path", "")
        try:
            if path and os.path.exists(path):
                shutil.rmtree(path, ignore_errors=False)
                logger.info("Session cleaned: %s | path=%s", session_id, path)
            else:
                logger.debug("Session %s had no temp dir to clean", session_id)
        except Exception as exc:
            logger.error(
                "Failed to clean session %s at %s: %s", session_id, path, exc
            )
        self.cleanup_count += 1
        return True

    def cleanup_expired_sessions(self) -> int:
        """Scan all sessions and delete those whose TTL has elapsed.

        Returns the number of sessions that were cleaned up.
        """
        from core.config import SESSION_TTL

        now = time.time()
        expired = [
            sid
            for sid, data in list(self._sessions.items())
            if now - data.get("created_at", now) > SESSION_TTL
        ]
        for sid in expired:
            logger.info(
                "Expiring session %s (age=%.0fs, ttl=%ds)",
                sid, now - self._sessions[sid]["created_at"], SESSION_TTL,
            )
            self.delete(sid)

        if expired:
            logger.info(
                "Cleanup pass complete: removed %d expired session(s) | active=%d",
                len(expired), self.active_sessions,
            )
        return len(expired)

    def cleanup_all(self) -> int:
        """Delete every session — called during graceful shutdown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            self.delete(sid)
        logger.info("All sessions cleaned up (%d total)", len(session_ids))
        return len(session_ids)

    def metrics(self) -> dict:
        """Return a snapshot of session metrics."""
        return {
            "active_sessions": self.active_sessions,
            "total_sessions": self.total_sessions,
            "cleanup_count": self.cleanup_count,
        }


# ---------------------------------------------------------------------------
# Singleton session store
# ---------------------------------------------------------------------------

session_manager = SessionManager()

# Backward-compatible alias so existing routes.py imports keep working.
temp_dirs = session_manager


# ---------------------------------------------------------------------------
# Filename / session-ID validation helpers
# ---------------------------------------------------------------------------

def validate_filename(filename: str) -> str:
    """Security: prevent directory traversal and strip invalid characters."""
    safe_name = os.path.basename(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9.\-_ ()]', '_', safe_name)
    if not safe_name or safe_name.startswith('.'):
        safe_name = f"unnamed_file_{secrets.token_hex(4)}"
    return safe_name


def validate_session_id(session_id: str) -> None:
    """Security: validate UUID format to prevent path traversal via session_id."""
    pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
    if not re.match(pattern, session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")


def validate_session_token(session_id: str, auth_header: str) -> dict:
    """Security: verify the bearer token matches the stored hash for this session."""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication")

    token = auth_header.split(" ")[1]
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    if session_id not in session_manager:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    session = session_manager[session_id]
    if session["token_hash"] != token_hash:
        raise HTTPException(status_code=403, detail="Invalid session token")

    # Refresh last-accessed timestamp
    session["last_accessed_at"] = time.time()
    return session


def generate_session_token() -> str:
    """Generate a cryptographically secure random bearer token."""
    return secrets.token_urlsafe(32)
