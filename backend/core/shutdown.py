"""
core/shutdown.py
~~~~~~~~~~~~~~~~
Graceful shutdown handler for the VR Saree Sorter backend.

Responsibilities
----------------
- cleanup_all_sessions()  – delete every live session's temp files
- shutdown_ocr_pool()     – drain and release all OCR engine instances
- stop_monitoring()       – cancel the background resource-monitoring task
- run_shutdown_sequence() – orchestrate all of the above in the correct order

``run_shutdown_sequence()`` is called from main.py's ``lifespan`` handler
on application exit.  It is designed to be idempotent and exception-safe so
that a partial failure in one step does not prevent the others from running.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("vr-saree-sorter.shutdown")


# ---------------------------------------------------------------------------
# Individual shutdown steps
# ---------------------------------------------------------------------------

def cleanup_all_sessions() -> int:
    """Delete temp files for every live session.

    Returns the number of sessions cleaned up.
    """
    try:
        from core.security import session_manager
        count = session_manager.cleanup_all()
        logger.info("Shutdown: cleaned up %d session(s)", count)
        return count
    except Exception as exc:
        logger.error("Shutdown: error cleaning sessions: %s", exc)
        return 0


def shutdown_ocr_pool() -> None:
    """Drain the OCR engine pool and release all engine instances.

    RapidOCR engines do not expose an explicit ``close()`` method, so we
    simply drain the queue so the objects become eligible for GC.
    """
    try:
        from scanner.engine_pool import ocr_pool
        import queue as _queue

        drained = 0
        while True:
            try:
                ocr_pool.pool.get_nowait()
                drained += 1
            except _queue.Empty:
                break

        ocr_pool._initialized = False
        logger.info("Shutdown: OCR pool drained (%d engine slot(s) released)", drained)
    except Exception as exc:
        logger.error("Shutdown: error draining OCR pool: %s", exc)


def stop_monitoring() -> None:
    """Cancel the background resource-monitoring asyncio task."""
    try:
        from core.monitoring import stop_monitoring_task
        stop_monitoring_task()
        logger.info("Shutdown: resource monitoring stopped")
    except Exception as exc:
        logger.error("Shutdown: error stopping monitoring: %s", exc)


def close_database_connections() -> None:
    """Placeholder for future database connection teardown (Phase 3).

    When a real database is added, close connection pools here.
    """
    logger.info("Shutdown: no database connections to close (Phase 3 pending)")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_shutdown_sequence() -> None:
    """Run all shutdown steps in order, logging each one.

    This function is exception-safe: a failure in one step is logged but
    does not prevent subsequent steps from running.
    """
    t0 = time.monotonic()
    logger.info("=== Graceful shutdown sequence starting ===")

    steps = [
        ("stop_monitoring", stop_monitoring),
        ("cleanup_all_sessions", cleanup_all_sessions),
        ("shutdown_ocr_pool", shutdown_ocr_pool),
        ("close_database_connections", close_database_connections),
    ]

    for name, fn in steps:
        try:
            fn()
        except Exception as exc:
            logger.error("Shutdown step '%s' raised: %s", name, exc)

    elapsed = round(time.monotonic() - t0, 3)
    logger.info("=== Graceful shutdown complete in %.3fs ===", elapsed)
