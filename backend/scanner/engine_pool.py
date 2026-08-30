import queue
import logging
import os
from rapidocr_onnxruntime import RapidOCR
from core.config import OCR_POOL_SIZE, OCR_THREADS_PER_ENGINE

logger = logging.getLogger("vr-saree-sorter.pool")

class RapidsEnginePool:
    def __init__(self, size=None):
        # Default size comes from central config (set to 1 for safety)
        self.size = size or OCR_POOL_SIZE
        self.pool = queue.Queue(maxsize=self.size)
        self._initialized = False

    def initialize(self):
        """Pre-fill the pool with None for lazy initialization"""
        if self._initialized:
            return

        logger.info("Setting up RapidOCR pool of size %d...", self.size)
        for i in range(self.size):
            self.pool.put(None)
        self._initialized = True
        logger.info("RapidOCR pool initialized.")

    def _create_engine(self) -> RapidOCR:
        logger.info("Instantiating RapidOCR ONNX engine...")
        return RapidOCR(
            det_limit_side_len=960,
            text_score=0.4,
            intra_op_num_threads=OCR_THREADS_PER_ENGINE,
            inter_op_num_threads=OCR_THREADS_PER_ENGINE,
        )

    def warm_up(self, count: int = 1):
        """Pre-instantiate engines so the first user request experiences zero cold-start delay."""
        if not self._initialized:
            self.initialize()

        warmed = []
        for _ in range(min(count, self.size)):
            eng = self.pool.get()
            if eng is None:
                eng = self._create_engine()
            warmed.append(eng)

        for eng in warmed:
            self.pool.put(eng)
        logger.info("RapidOCR pool pre-warmed with %d engine(s).", len(warmed))

    def acquire(self) -> RapidOCR:
        if not self._initialized:
            self.initialize()

        engine = self.pool.get()
        if engine is None:
            engine = self._create_engine()
        return engine

    def release(self, engine: RapidOCR):
        self.pool.put(engine)

# Singleton pool
ocr_pool = RapidsEnginePool()
