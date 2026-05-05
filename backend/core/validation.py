"""
core/validation.py — Comprehensive input validation, checksum verification,
and idempotency key tracking.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("vr-saree-sorter.validation")

# ---------------------------------------------------------------------------
# Idempotency key store
# Maps SHA-256(image_bytes) → (result, timestamp)
# Prevents re-processing identical images within the same process lifetime.
# ---------------------------------------------------------------------------
_idempotency_cache: Dict[str, Tuple[Optional[str], float]] = {}

# Maximum number of entries kept in the idempotency cache.
_IDEMPOTENCY_CACHE_MAX = 10_000
# How long (seconds) an idempotency entry is considered valid.
_IDEMPOTENCY_TTL = 3600


def compute_checksum(data: bytes) -> str:
    """Return the SHA-256 hex digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def check_idempotency(checksum: str) -> Tuple[bool, Optional[str]]:
    """
    Check whether *checksum* has already been processed.

    Returns:
        (True, cached_result)  — if a cached result exists and is still valid.
        (False, None)          — if this is a new / expired entry.
    """
    entry = _idempotency_cache.get(checksum)
    if entry is None:
        return False, None
    result, ts = entry
    if time.time() - ts > _IDEMPOTENCY_TTL:
        # Expired — treat as new
        del _idempotency_cache[checksum]
        return False, None
    return True, result


def record_idempotency(checksum: str, result: Optional[str]) -> None:
    """
    Store the processing *result* for *checksum* so future identical images
    can be served from cache without re-running OCR/barcode scanning.
    Evicts the oldest entry when the cache is full.
    """
    if len(_idempotency_cache) >= _IDEMPOTENCY_CACHE_MAX:
        # Evict the oldest entry (insertion-order preserved in Python 3.7+)
        oldest_key = next(iter(_idempotency_cache))
        del _idempotency_cache[oldest_key]
    _idempotency_cache[checksum] = (result, time.time())


def purge_expired_idempotency_entries() -> int:
    """Remove all expired entries from the idempotency cache. Returns count removed."""
    cutoff = time.time() - _IDEMPOTENCY_TTL
    expired = [k for k, (_, ts) in list(_idempotency_cache.items()) if ts < cutoff]
    for k in expired:
        del _idempotency_cache[k]
    return len(expired)


# ---------------------------------------------------------------------------
# Image integrity validation
# ---------------------------------------------------------------------------

def validate_image_bytes(contents: bytes, max_dimension: int = 8000) -> Tuple[bool, str]:
    """
    Validate that *contents* is a decodable, non-corrupt image within the
    allowed dimension bounds.

    Returns:
        (True, "")            — valid image.
        (False, error_msg)    — invalid, with a human-readable reason.
    """
    try:
        from PIL import Image
        import io

        image = Image.open(io.BytesIO(contents))
        width, height = image.size
        image.verify()  # Raises on corrupt data; invalidates the object

        if width > max_dimension or height > max_dimension:
            return False, (
                f"Image dimensions {width}×{height} exceed the maximum "
                f"allowed {max_dimension}px on either axis."
            )
        return True, ""
    except Exception as exc:
        return False, f"Invalid or corrupted image: {type(exc).__name__}"


# ---------------------------------------------------------------------------
# Parameter bounds checking
# ---------------------------------------------------------------------------

def clamp(value: int, lo: int, hi: int, name: str = "value") -> int:
    """Return *value* clamped to [lo, hi], logging a warning if clamped."""
    if value < lo:
        logger.warning("%s=%d is below minimum %d; clamping to %d", name, value, lo, lo)
        return lo
    if value > hi:
        logger.warning("%s=%d exceeds maximum %d; clamping to %d", name, value, hi, hi)
        return hi
    return value


# ---------------------------------------------------------------------------
# Idempotency cache metrics
# ---------------------------------------------------------------------------

def idempotency_metrics() -> dict:
    """Return a snapshot of the idempotency cache state."""
    return {
        "cache_size": len(_idempotency_cache),
        "cache_max": _IDEMPOTENCY_CACHE_MAX,
        "ttl_seconds": _IDEMPOTENCY_TTL,
    }
