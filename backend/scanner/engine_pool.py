import queue
import logging
from rapidocr_onnxruntime import RapidOCR
from core.config import BATCH_CONCURRENCY

logger = logging.getLogger("vr-saree-sorter.pool")

class RapidsEnginePool:
    def __init__(self, size=None):
        self.size = size or max(2, BATCH_CONCURRENCY // 2)
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
