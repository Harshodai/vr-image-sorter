"""
core/logger.py
~~~~~~~~~~~~~~
Centralised logging configuration for the VR Saree Sorter backend.

Features
--------
- Structured format with timestamp, logger name, level, and correlation ID
  (when present in the log record's ``extra`` dict).
- Log rotation: 10 MB per file, 5 backup files kept, written to ``logs/``.
- A ``get_logger`` helper that child modules should use so every logger
  inherits the same handlers and format.
- A ``bind_correlation_id`` context helper for per-request tracing.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import uuid
from contextvars import ContextVar

# ---------------------------------------------------------------------------
# Correlation-ID context variable
# ---------------------------------------------------------------------------

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def new_correlation_id() -> str:
    """Generate and store a fresh correlation ID for the current async context."""
    cid = uuid.uuid4().hex[:12]
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    """Return the correlation ID bound to the current async context."""
    return _correlation_id.get()


# ---------------------------------------------------------------------------
# Custom formatter that injects the correlation ID
# ---------------------------------------------------------------------------

class CorrelationFormatter(logging.Formatter):
    """Formatter that appends the per-request correlation ID to every line."""

    def format(self, record: logging.LogRecord) -> str:
        record.correlation_id = _correlation_id.get()
        return super().format(record)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | cid=%(correlation_id)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_LOG_DIR = os.environ.get("LOG_DIR", "logs")
_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


def _setup_logging() -> None:
    """Configure root logger with console + rotating-file handlers."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))

    formatter = CorrelationFormatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler (skip if log dir cannot be created, e.g. read-only FS)
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(_LOG_DIR, "app.log"),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("Could not create log directory '%s'; file logging disabled.", _LOG_DIR)


_setup_logging()

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the ``vr-saree-sorter`` namespace."""
    return logging.getLogger(f"vr-saree-sorter.{name}" if not name.startswith("vr-saree-sorter") else name)


# Root application logger — kept for backward compatibility with existing imports.
logger = logging.getLogger("vr-saree-sorter")

