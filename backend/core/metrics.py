"""
core/metrics.py — Lightweight in-process request and resource metrics.

Collected metrics:
  - requests_total        : total requests received
  - requests_success      : requests that returned HTTP 2xx
  - requests_failed       : requests that returned HTTP 4xx/5xx
  - images_processed      : individual images successfully identified
  - images_failed         : individual images that could not be identified
  - idempotency_hits      : images served from the idempotency cache
  - processing_time_total : cumulative seconds spent in scan_in_thread
  - active_sessions       : current number of live sessions (sampled)

All counters are process-local integers — no external dependency required.
For multi-worker Gunicorn deployments each worker maintains its own counters;
the /metrics endpoint aggregates the current worker's view only.
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Dict, Any

_lock = Lock()

_counters: Dict[str, float] = {
    "requests_total": 0,
    "requests_success": 0,
    "requests_failed": 0,
    "images_processed": 0,
    "images_failed": 0,
    "idempotency_hits": 0,
    "processing_time_total": 0.0,
}

_start_time: float = time.time()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def increment(counter: str, amount: float = 1.0) -> None:
    """Thread-safe counter increment."""
    with _lock:
        if counter in _counters:
            _counters[counter] += amount
        # Silently ignore unknown counters to avoid crashing hot paths.


def record_processing_time(seconds: float) -> None:
    """Add *seconds* to the cumulative processing time counter."""
    increment("processing_time_total", seconds)


def snapshot() -> Dict[str, Any]:
    """
    Return a point-in-time snapshot of all metrics.
    Includes derived values (uptime, average processing time).
    """
    from core.security import session_metrics
    from core.validation import idempotency_metrics

    with _lock:
        counters = dict(_counters)

    uptime = time.time() - _start_time
    total_images = counters["images_processed"] + counters["images_failed"]
    avg_time = (
        counters["processing_time_total"] / total_images
        if total_images > 0
        else 0.0
    )

    sess = session_metrics()
    idem = idempotency_metrics()

    return {
        "uptime_seconds": round(uptime, 1),
        **{k: int(v) if k != "processing_time_total" else round(v, 3)
           for k, v in counters.items()},
        "avg_processing_time_seconds": round(avg_time, 3),
        "active_sessions": sess["active_sessions"],
        "idempotency_cache_size": idem["cache_size"],
    }


def reset() -> None:
    """Reset all counters (useful in tests)."""
    with _lock:
        for k in _counters:
            _counters[k] = 0
    global _start_time
    _start_time = time.time()
