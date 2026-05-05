"""
core/monitoring.py
~~~~~~~~~~~~~~~~~~
Lightweight resource monitoring for the VR Saree Sorter backend.

Provides:
- get_memory_usage()   – current RSS memory as (percent, GB)
- get_cpu_usage()      – current process + system CPU %
- check_resource_health() – "healthy" | "warning" | "critical"
- log_resource_metrics()  – emit a structured INFO log line
- start_monitoring_task() – launch a background asyncio task that logs
                            every 30 seconds and warns on threshold breach

``psutil`` is used when available; if it is not installed the functions
degrade gracefully and return sentinel values so the rest of the app
continues to work.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Tuple

logger = logging.getLogger("vr-saree-sorter.monitoring")

# Monitoring interval in seconds
_MONITOR_INTERVAL = 30

# Try to import psutil; fall back gracefully if not installed
try:
    import psutil as _psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False
    logger.warning(
        "psutil is not installed — resource monitoring will return placeholder values. "
        "Add 'psutil' to requirements.txt for full monitoring support."
    )


# ---------------------------------------------------------------------------
# Core metric functions
# ---------------------------------------------------------------------------

def get_memory_usage() -> Tuple[float, float]:
    """Return ``(percent, gb)`` for the current process's RSS memory.

    Falls back to ``(0.0, 0.0)`` when psutil is unavailable.
    """
    if not _PSUTIL_AVAILABLE:
        return 0.0, 0.0
    try:
        process = _psutil.Process()
        rss_bytes = process.memory_info().rss
        total_bytes = _psutil.virtual_memory().total
        percent = (rss_bytes / total_bytes * 100) if total_bytes else 0.0
        gb = rss_bytes / (1024 ** 3)
        return round(percent, 1), round(gb, 3)
    except Exception as exc:
        logger.debug("get_memory_usage error: %s", exc)
        return 0.0, 0.0


def get_cpu_usage() -> float:
    """Return the system-wide CPU utilisation percentage (1-second interval).

    Falls back to ``0.0`` when psutil is unavailable.
    """
    if not _PSUTIL_AVAILABLE:
        return 0.0
    try:
        return _psutil.cpu_percent(interval=1)
    except Exception as exc:
        logger.debug("get_cpu_usage error: %s", exc)
        return 0.0


def check_resource_health() -> str:
    """Return a health string based on current memory and CPU usage.

    Returns
    -------
    "healthy"  – all metrics within normal bounds
    "warning"  – memory > MAX_MEMORY_PERCENT OR cpu > 90 %
    "critical" – memory > 95 % OR cpu > 98 %
    """
    from core.config import MAX_MEMORY_PERCENT

    mem_pct, _ = get_memory_usage()
    cpu_pct = get_cpu_usage()

    if mem_pct > 95 or cpu_pct > 98:
        return "critical"
    if mem_pct > MAX_MEMORY_PERCENT or cpu_pct > 90:
        return "warning"
    return "healthy"


def log_resource_metrics() -> dict:
    """Log current resource metrics and return them as a dict."""
    mem_pct, mem_gb = get_memory_usage()
    cpu_pct = get_cpu_usage()
    health = check_resource_health()

    from core.config import MAX_MEMORY_PERCENT
    from core.security import session_manager

    session_metrics = session_manager.metrics()

    metrics = {
        "memory_percent": mem_pct,
        "memory_gb": mem_gb,
        "cpu_percent": cpu_pct,
        "health": health,
        **session_metrics,
    }

    log_fn = logger.warning if health != "healthy" else logger.info
    log_fn(
        "Resource metrics | mem=%.1f%% (%.3fGB) cpu=%.1f%% health=%s "
        "active_sessions=%d total_sessions=%d cleanup_count=%d",
        mem_pct, mem_gb, cpu_pct, health,
        session_metrics["active_sessions"],
        session_metrics["total_sessions"],
        session_metrics["cleanup_count"],
    )

    if mem_pct > MAX_MEMORY_PERCENT:
        logger.warning(
            "ALERT: Memory usage %.1f%% exceeds threshold %d%%",
            mem_pct, MAX_MEMORY_PERCENT,
        )
    if cpu_pct > 90:
        logger.warning("ALERT: CPU usage %.1f%% exceeds 90%% threshold", cpu_pct)

    return metrics


# ---------------------------------------------------------------------------
# Background monitoring task
# ---------------------------------------------------------------------------

_monitoring_task: asyncio.Task | None = None


async def _monitoring_loop() -> None:
    """Async loop that logs resource metrics every ``_MONITOR_INTERVAL`` seconds."""
    logger.info("Resource monitoring started (interval=%ds)", _MONITOR_INTERVAL)
    while True:
        try:
            await asyncio.sleep(_MONITOR_INTERVAL)
            log_resource_metrics()
        except asyncio.CancelledError:
            logger.info("Resource monitoring task cancelled")
            break
        except Exception as exc:
            logger.error("Monitoring loop error: %s", exc)


def start_monitoring_task() -> asyncio.Task:
    """Schedule the background monitoring loop and return the Task.

    Safe to call multiple times — only one task is ever running.
    """
    global _monitoring_task
    if _monitoring_task is not None and not _monitoring_task.done():
        return _monitoring_task
    _monitoring_task = asyncio.create_task(_monitoring_loop(), name="resource-monitor")
    return _monitoring_task


def stop_monitoring_task() -> None:
    """Cancel the background monitoring task if it is running."""
    global _monitoring_task
    if _monitoring_task and not _monitoring_task.done():
        _monitoring_task.cancel()
        logger.info("Resource monitoring task stop requested")
    _monitoring_task = None
