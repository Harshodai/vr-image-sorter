from __future__ import annotations

import logging
import queue
import time
from typing import Optional

from rapidocr_onnxruntime import RapidOCR

from core.config import OCR_POOL_SIZE

logger = logging.getLogger("vr-saree-sorter.pool")


class RapidsEnginePool:
    """
    Thread-safe object pool for RapidOCR engine instances.

    Engines are lazily initialised on first acquire to avoid blocking the
    process startup path.  The pool size is bounded by OCR_POOL_SIZE (default 1)
    which prevents resource exhaustion in multi-worker Gunicorn deployments.
    """

    def __init__(self, size: Optional[int] = None) -> None:
        # Default size comes from central config (set to 1 for safety)
        self.size: int = size or OCR_POOL_SIZE
        self.pool: queue.Queue = queue.Queue(maxsize=self.size)
        self._initialized: bool = False
        self._healthy: bool = True  # flipped to False if health check fails

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Pre-fill the pool with sentinel None values for lazy initialisation."""
        if self._initialized:
            return

        logger.info("Setting up lazy RapidOCR pool of size %d…", self.size)
        for _ in range(self.size):
            self.pool.put(None)
        self._initialized = True
        logger.info("RapidOCR pool initialised (size=%d).", self.size)

    def shutdown(self) -> None:
        """
        Drain the pool and release all engine resources.
        Called during graceful shutdown so ONNX sessions are closed cleanly.
        """
        logger.info("Shutting down RapidOCR pool…")
        drained = 0
        while not self.pool.empty():
            try:
                engine = self.pool.get_nowait()
                # RapidOCR does not expose an explicit close() — the ONNX
                # InferenceSession is released when the object is GC'd.
                del engine
                drained += 1
            except queue.Empty:
                break
        self._initialized = False
        logger.info("RapidOCR pool shut down (%d engine(s) released).", drained)

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    def acquire(self, timeout: float = 30.0) -> RapidOCR:
        """
        Borrow an engine from the pool.  Blocks for up to *timeout* seconds
        if all engines are in use.  Raises ``queue.Empty`` on timeout.
        """
        if not self._initialized:
            self.initialize()

        engine = self.pool.get(timeout=timeout)
        if engine is None:
            logger.info("Lazy-loading RapidOCR engine…")
            # det_limit_side_len=960: Higher detection resolution for small label text.
            # text_score=0.4: Lower threshold catches more candidates (VR filter handles precision).
            # Benchmark-verified: 36% faster than defaults, same 100% accuracy.
            engine = RapidOCR(det_limit_side_len=960, text_score=0.4)
        return engine

    def release(self, engine: RapidOCR) -> None:
        """Return *engine* to the pool."""
        self.pool.put(engine)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """
        Acquire an engine, run a trivial inference, and release it.
        Returns True if the engine is responsive, False otherwise.
        Updates the internal ``_healthy`` flag.
        """
        import numpy as np

        try:
            engine = self.acquire(timeout=5.0)
            try:
                dummy = np.full((32, 128, 3), 255, dtype=np.uint8)
                engine(dummy)
                self._healthy = True
            finally:
                self.release(engine)
        except Exception as exc:
            logger.error("OCR engine health check failed: %s", exc)
            self._healthy = False
        return self._healthy

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def metrics(self) -> dict:
        """Return a snapshot of pool utilisation."""
        available = self.pool.qsize()
        return {
            "pool_size": self.size,
            "available_engines": available,
            "in_use_engines": self.size - available,
            "initialized": self._initialized,
            "healthy": self._healthy,
        }


# Singleton pool — one per worker process in Gunicorn deployments.
ocr_pool = RapidsEnginePool()
