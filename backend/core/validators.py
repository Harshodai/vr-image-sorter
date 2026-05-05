"""
core/validators.py
~~~~~~~~~~~~~~~~~~
Configuration validators called at startup to catch misconfigured environment
variables before they cause silent failures at runtime.

Each validator raises ``ValueError`` with a human-readable message that
includes the offending value and the acceptable range.
"""

from __future__ import annotations


def validate_ocr_pool_size(value: int) -> int:
    """OCR_POOL_SIZE must be between 1 and 8 (inclusive)."""
    if not (1 <= value <= 8):
        raise ValueError(
            f"OCR_POOL_SIZE={value} is out of range. "
            "Accepted range: 1–8. "
            "Recommended: number of CPU cores / 2."
        )
    return value


def validate_batch_concurrency(value: int, ocr_pool_size: int) -> int:
    """BATCH_CONCURRENCY must be between 1 and 32 and >= OCR_POOL_SIZE."""
    if not (1 <= value <= 32):
        raise ValueError(
            f"BATCH_CONCURRENCY={value} is out of range. "
            "Accepted range: 1–32."
        )
    if value < ocr_pool_size:
        raise ValueError(
            f"BATCH_CONCURRENCY={value} must be >= OCR_POOL_SIZE={ocr_pool_size}. "
            "Every OCR engine needs at least one concurrency slot. "
            f"Set BATCH_CONCURRENCY to at least {ocr_pool_size}."
        )
    return value


def validate_max_batch_size(value: int) -> int:
    """MAX_BATCH_SIZE must be between 1 and 5000 (inclusive)."""
    if not (1 <= value <= 5000):
        raise ValueError(
            f"MAX_BATCH_SIZE={value} is out of range. "
            "Accepted range: 1–5000."
        )
    return value


def validate_session_ttl(value: int) -> int:
    """SESSION_TTL must be between 300 (5 min) and 86400 (24 hours)."""
    if not (300 <= value <= 86400):
        raise ValueError(
            f"SESSION_TTL={value}s is out of range. "
            "Accepted range: 300–86400 seconds (5 minutes to 24 hours)."
        )
    return value


def validate_session_cleanup_interval(value: int) -> int:
    """SESSION_CLEANUP_INTERVAL must be between 60 (1 min) and 3600 (1 hour)."""
    if not (60 <= value <= 3600):
        raise ValueError(
            f"SESSION_CLEANUP_INTERVAL={value}s is out of range. "
            "Accepted range: 60–3600 seconds (1 minute to 1 hour)."
        )
    return value


def validate_max_memory_percent(value: int) -> int:
    """MAX_MEMORY_PERCENT must be between 50 and 95 (inclusive)."""
    if not (50 <= value <= 95):
        raise ValueError(
            f"MAX_MEMORY_PERCENT={value} is out of range. "
            "Accepted range: 50–95. "
            "Values below 50 will cause excessive request rejection; "
            "values above 95 risk OOM kills."
        )
    return value


def validate_worker_timeout(value: int) -> int:
    """WORKER_TIMEOUT must be between 30 and 300 seconds (inclusive)."""
    if not (30 <= value <= 300):
        raise ValueError(
            f"WORKER_TIMEOUT={value}s is out of range. "
            "Accepted range: 30–300 seconds."
        )
    return value


def validate_max_concurrent_sessions(value: int) -> int:
    """MAX_CONCURRENT_SESSIONS must be between 10 and 10000 (inclusive)."""
    if not (10 <= value <= 10000):
        raise ValueError(
            f"MAX_CONCURRENT_SESSIONS={value} is out of range. "
            "Accepted range: 10–10000."
        )
    return value


def validate_all(cfg) -> None:  # cfg is the core.config module
    """Run every validator against the resolved config module.

    Raises ``ValueError`` on the first constraint violation found.
    Call this once during application startup before serving traffic.
    """
    validate_ocr_pool_size(cfg.OCR_POOL_SIZE)
    validate_batch_concurrency(cfg.BATCH_CONCURRENCY, cfg.OCR_POOL_SIZE)
    validate_max_batch_size(cfg.MAX_BATCH_SIZE)
    validate_session_ttl(cfg.SESSION_TTL)
    validate_session_cleanup_interval(cfg.SESSION_CLEANUP_INTERVAL)
    validate_max_memory_percent(cfg.MAX_MEMORY_PERCENT)
    validate_worker_timeout(cfg.WORKER_TIMEOUT)
    validate_max_concurrent_sessions(cfg.MAX_CONCURRENT_SESSIONS)
