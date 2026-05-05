"""
core/startup.py — Intelligent startup validation and graceful shutdown.

Runs during the FastAPI lifespan to:
  1. Log the full resolved configuration.
  2. Validate that the OCR engine pool can be initialised.
  3. Check available system resources and warn on constraints.
  4. Start the background session-cleanup task.
  5. Register a graceful shutdown handler that drains the pool cleanly.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

logger = logging.getLogger("vr-saree-sorter.startup")


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------

def _get_memory_info() -> dict:
    """Return available / total memory in MB (best-effort, no hard dependency)."""
    try:
        import psutil  # type: ignore
        vm = psutil.virtual_memory()
        return {
            "total_mb": vm.total // (1024 * 1024),
            "available_mb": vm.available // (1024 * 1024),
            "percent_used": vm.percent,
        }
    except ImportError:
        # psutil is optional — fall back to /proc/meminfo on Linux
        try:
            mem: dict = {}
            with open("/proc/meminfo") as fh:
                for line in fh:
                    parts = line.split()
                    if parts[0] in ("MemTotal:", "MemAvailable:"):
                        mem[parts[0].rstrip(":")] = int(parts[1]) // 1024  # kB → MB
            return {
                "total_mb": mem.get("MemTotal", 0),
                "available_mb": mem.get("MemAvailable", 0),
                "percent_used": round(
                    100 * (1 - mem.get("MemAvailable", 0) / max(mem.get("MemTotal", 1), 1)), 1
                ),
            }
        except Exception:
            return {"total_mb": 0, "available_mb": 0, "percent_used": 0}


def _get_disk_info(path: str = "/tmp") -> dict:
    """Return free disk space in MB for the given path."""
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_mb": usage.total // (1024 * 1024),
            "free_mb": usage.free // (1024 * 1024),
        }
    except Exception:
        return {"total_mb": 0, "free_mb": 0}


# ---------------------------------------------------------------------------
# Configuration summary logger
# ---------------------------------------------------------------------------

def log_config_summary() -> None:
    """Emit a structured summary of all resolved configuration values."""
    from core.config import (
        OCR_POOL_SIZE, BATCH_CONCURRENCY, MAX_BATCH_SIZE,
        REQUEST_QUEUE_SIZE, REQUEST_TIMEOUT, SESSION_TTL,
        CLEANUP_INTERVAL, ENABLE_BARCODE_SCANNER, ENABLE_METRICS,
        MAX_FILE_SIZE, MAX_TOTAL_SIZE, MAX_IMAGE_DIMENSION,
        MAX_DOWNLOADS_PER_SESSION, PORT,
    )

    mem = _get_memory_info()
    disk = _get_disk_info()

    logger.info("=" * 60)
    logger.info("VR Image Sorter — startup configuration")
    logger.info("=" * 60)
    logger.info("  PORT                    : %s", PORT)
    logger.info("  OCR_POOL_SIZE           : %d", OCR_POOL_SIZE)
    logger.info("  BATCH_CONCURRENCY       : %d", BATCH_CONCURRENCY)
    logger.info("  MAX_BATCH_SIZE          : %d", MAX_BATCH_SIZE)
    logger.info("  REQUEST_QUEUE_SIZE      : %d", REQUEST_QUEUE_SIZE)
    logger.info("  REQUEST_TIMEOUT         : %ds", REQUEST_TIMEOUT)
    logger.info("  SESSION_TTL             : %ds", SESSION_TTL)
    logger.info("  CLEANUP_INTERVAL        : %ds", CLEANUP_INTERVAL)
    logger.info("  ENABLE_BARCODE_SCANNER  : %s", ENABLE_BARCODE_SCANNER)
    logger.info("  ENABLE_METRICS          : %s", ENABLE_METRICS)
    logger.info("  MAX_FILE_SIZE           : %d MB", MAX_FILE_SIZE // (1024 * 1024))
    logger.info("  MAX_TOTAL_SIZE          : %d MB", MAX_TOTAL_SIZE // (1024 * 1024))
    logger.info("  MAX_IMAGE_DIMENSION     : %dpx", MAX_IMAGE_DIMENSION)
    logger.info("  MAX_DOWNLOADS_PER_SESSION: %d", MAX_DOWNLOADS_PER_SESSION)
    logger.info("-" * 60)
    if mem["total_mb"]:
        logger.info(
            "  System memory: %d MB total, %d MB available (%.1f%% used)",
            mem["total_mb"], mem["available_mb"], mem["percent_used"],
        )
        if mem["available_mb"] and mem["available_mb"] < 256:
            logger.warning(
                "  ⚠  Low available memory (%d MB). Consider reducing OCR_POOL_SIZE "
                "or BATCH_CONCURRENCY to avoid OOM kills.",
                mem["available_mb"],
            )
    if disk["total_mb"]:
        logger.info(
            "  /tmp disk: %d MB total, %d MB free",
            disk["total_mb"], disk["free_mb"],
        )
        if disk["free_mb"] and disk["free_mb"] < 512:
            logger.warning(
                "  ⚠  Low /tmp disk space (%d MB free). Large batches may fail.",
                disk["free_mb"],
            )
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# OCR engine health check
# ---------------------------------------------------------------------------

def validate_ocr_engine() -> bool:
    """
    Attempt to initialise one OCR engine and run a trivial inference to
    confirm the ONNX models are present and loadable.
    Returns True on success, False on failure (non-fatal — service degrades).
    """
    try:
        from scanner.engine_pool import ocr_pool
        ocr_pool.initialize()
        engine = ocr_pool.acquire()
        # Minimal 1×1 white image — just enough to exercise the ONNX session
        import numpy as np
        dummy = np.full((32, 128, 3), 255, dtype=np.uint8)
        engine(dummy)
        ocr_pool.release(engine)
        logger.info("✅ OCR engine health check passed")
        return True
    except Exception as exc:
        logger.error("❌ OCR engine health check failed: %s", exc, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Background session cleanup task
# ---------------------------------------------------------------------------

async def _session_cleanup_loop() -> None:
    """Periodically expire sessions that have exceeded SESSION_TTL."""
    from core.config import SESSION_TTL, CLEANUP_INTERVAL
    from core.security import cleanup_expired_sessions

    logger.info("Session cleanup task started (interval=%ds, TTL=%ds)", CLEANUP_INTERVAL, SESSION_TTL)
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)
            removed = cleanup_expired_sessions(SESSION_TTL)
            if removed:
                logger.info("Session cleanup: removed %d expired session(s)", removed)
        except asyncio.CancelledError:
            logger.info("Session cleanup task cancelled — shutting down")
            break
        except Exception as exc:
            logger.error("Session cleanup error: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Lifespan context manager (FastAPI ≥ 0.93)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app) -> AsyncGenerator[None, None]:  # type: ignore[type-arg]
    """
    FastAPI lifespan handler.
    Everything before `yield` runs at startup; everything after at shutdown.
    """
    # ── Startup ──────────────────────────────────────────────────────────
    log_config_summary()

    ocr_ok = validate_ocr_engine()
    if not ocr_ok:
        logger.warning(
            "OCR engine failed to initialise. The service will start but OCR "
            "fallback will be unavailable until the engine recovers."
        )

    cleanup_task = asyncio.create_task(_session_cleanup_loop())
    logger.info("Application startup complete")

    yield  # ── Application runs here ──────────────────────────────────────

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Shutting down — cancelling background tasks...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Drain the OCR engine pool cleanly
    try:
        from scanner.engine_pool import ocr_pool
        ocr_pool.shutdown()
    except Exception as exc:
        logger.error("OCR pool shutdown error: %s", exc)

    # Final cleanup pass: remove all remaining sessions
    try:
        from core.security import cleanup_all_sessions
        removed = cleanup_all_sessions()
        if removed:
            logger.info("Shutdown cleanup: removed %d session(s)", removed)
    except Exception as exc:
        logger.error("Shutdown cleanup error: %s", exc)

    logger.info("Shutdown complete")
