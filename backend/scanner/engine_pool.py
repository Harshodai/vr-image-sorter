import queue
import logging
import os
from rapidocr_onnxruntime import RapidOCR
from core.config import OCR_POOL_SIZE

logger = logging.getLogger("vr-saree-sorter.pool")

class RapidsEnginePool:
    def __init__(self, size=None):
        # Default size comes from central config (set to 1 for safety)
        self.size = size or OCR_POOL_SIZE
        self.pool = queue.Queue(maxsize=self.size)
        self._initialized = False

    def initialize(self):
        """Pre-warm the OCR pool on startup"""
        if self._initialized:
            return
        
        logger.info(f"Pre-warming RapidOCR pool of size {self.size}...")
        for i in range(self.size):
            self.pool.put(RapidOCR())
        self._initialized = True
        logger.info("RapidOCR pool initialized.")

    def acquire(self) -> RapidOCR:
        if not self._initialized:
            self.initialize()
        return self.pool.get()

    def release(self, engine: RapidOCR):
        self.pool.put(engine)

# Singleton pool
ocr_pool = RapidsEnginePool()
