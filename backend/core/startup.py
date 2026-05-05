"""
core/startup.py
~~~~~~~~~~~~~~~
Intelligent startup validation for the VR Saree Sorter backend.

Performs the following checks before the application begins serving traffic:

1. Validate all configuration values (via core.validators)
2. Check available system memory and CPU cores
3. Validate that the temp directory is writable
4. Pre-warm the OCR engine pool
5. Log all startup parameters

``run_startup_checks()`` is the single entry-point called from main.py's
``lifespan`` handler.  It returns a status dict so callers can inspect
individual check results.  A ``RuntimeError`` is raised if any *critical*
check fails so the process exits cleanly rather than serving broken traffic.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Any, Dict

logger = logging.getLogger("vr-saree-sorter.startup")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_config() -> Dict[str, Any]:
    """Validate all configuration values.  Returns a result dict."""
    import core.config as cfg
    from core.validators import validate_all

    result: Dict[str, Any] = {"name": "config", "status": "ok", "detail": None}
    try:
        validate_all(cfg)
        cfg.log_config()
    except ValueError as exc:
        result["status"] = "failed"
        result["detail"] = str(exc)
        result["critical"] = True
    return result


def _check_system_resources() -> Dict[str, Any]:
    """Check available RAM and CPU cores; warn but don't fail."""
    result: Dict[str, Any] = {"name": "system_resources", "status": "ok", "detail": {}}

    cpu_count = os.cpu_count() or 1
    result["detail"]["cpu_cores"] = cpu_count

    try:
        import psutil
        vm = psutil.virtual_memory()
        available_gb = round(vm.available / (1024 ** 3), 2)
        total_gb = round(vm.total / (1024 ** 3), 2)
        result["detail"]["memory_available_gb"] = available_gb
        result["detail"]["memory_total_gb"] = total_gb

        if available_gb < 0.5:
            result["status"] = "warning"
            result["detail"]["warning"] = f"Only {available_gb}GB RAM available"
            logger.warning("Low available memory at startup: %.2fGB", available_gb)
        else:
            logger.info(
                "System resources: %d CPU cores, %.2fGB / %.2fGB RAM available",
                cpu_count, available_gb, total_gb,
            )
    except ImportError:
        result["detail"]["memory_available_gb"] = "unknown (psutil not installed)"
        logger.info("System resources: %d CPU cores (psutil not installed for RAM check)", cpu_count)

    return result


def _check_temp_directory() -> Dict[str, Any]:
    """Verify the system temp directory is writable."""
    result: Dict[str, Any] = {"name": "temp_directory", "status": "ok", "detail": None}
    try:
        with tempfile.NamedTemporaryFile(delete=True) as tmp:
            tmp.write(b"startup-check")
        result["detail"] = tempfile.gettempdir()
        logger.info("Temp directory writable: %s", tempfile.gettempdir())
    except Exception as exc:
        result["status"] = "failed"
        result["detail"] = str(exc)
        result["critical"] = True
        logger.error("Temp directory is not writable: %s", exc)
    return result


def _check_ocr_pool() -> Dict[str, Any]:
    """Pre-warm the OCR engine pool and verify at least one engine loads."""
    result: Dict[str, Any] = {"name": "ocr_pool", "status": "ok", "detail": None}
    try:
        from scanner.engine_pool import ocr_pool
        ocr_pool.initialize()
        result["detail"] = f"Pool size: {ocr_pool.size}"
        logger.info("OCR pool pre-warmed: %d engine slot(s)", ocr_pool.size)
    except Exception as exc:
        result["status"] = "failed"
        result["detail"] = str(exc)
        result["critical"] = True
        logger.error("OCR pool initialization failed: %s", exc, exc_info=True)
    return result


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def run_startup_checks() -> Dict[str, Any]:
    """Run all startup checks and return a status dict.

    Raises ``RuntimeError`` if any critical check fails so the process
    exits before accepting traffic.

    Returns
    -------
    dict with keys:
        "ok"      – True if all critical checks passed
        "checks"  – list of individual check result dicts
        "elapsed" – total time taken in seconds
    """
    t0 = time.monotonic()
    logger.info("=== Startup checks beginning ===")

    checks = [
        _check_config,
        _check_system_resources,
        _check_temp_directory,
        _check_ocr_pool,
    ]

    results = []
    critical_failures = []

    for check_fn in checks:
        try:
            res = check_fn()
        except Exception as exc:
            res = {
                "name": check_fn.__name__,
                "status": "error",
                "detail": str(exc),
                "critical": True,
            }
            logger.error("Startup check %s raised unexpectedly: %s", check_fn.__name__, exc)

        results.append(res)
        status = res.get("status", "ok")
        name = res.get("name", check_fn.__name__)

        if status == "ok":
            logger.info("  [OK]      %s", name)
        elif status == "warning":
            logger.warning("  [WARNING] %s — %s", name, res.get("detail"))
        else:
            logger.error("  [FAILED]  %s — %s", name, res.get("detail"))
            if res.get("critical"):
                critical_failures.append(name)

    elapsed = round(time.monotonic() - t0, 3)
    all_ok = len(critical_failures) == 0

    logger.info(
        "=== Startup checks complete in %.3fs — %s ===",
        elapsed, "ALL OK" if all_ok else f"FAILED: {', '.join(critical_failures)}",
    )

    if not all_ok:
        raise RuntimeError(
            f"Critical startup checks failed: {', '.join(critical_failures)}. "
            "Review the logs above and fix the configuration before restarting."
        )

    return {"ok": True, "checks": results, "elapsed": elapsed}
