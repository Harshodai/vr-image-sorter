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
        
        logger.info(f"Setting up lazy RapidOCR pool of size {self.size}...")
        for i in range(self.size):
            self.pool.put(None)
        self._initialized = True
        logger.info("RapidOCR pool initialized.")

    def acquire(self) -> RapidOCR:
        if not self._initialized:
            self.initialize()
            
        engine = self.pool.get()
        if engine is None:
            logger.info("Lazy loading RapidOCR engine...")
            # det_limit_side_len=960: Higher detection resolution for small label text
            # text_score=0.4: Lower threshold catches more candidates (VR filter handles precision)
            # Benchmark-verified: 36% faster than defaults, same 100% accuracy
            # intra/inter_op_num_threads: ONNX Runtime defaults to -1 (= every core),
            # so a single process saturates the CPU and extra workers only contend —
            # measured 1.06 img/s at 1, 4 and 8 workers alike. Pinning each engine to
            # one thread lets process-level parallelism actually scale (2.03 img/s at
            # 10 workers on a 10-core host).
            engine = RapidOCR(
                det_limit_side_len=960,
                text_score=0.4,
                intra_op_num_threads=OCR_THREADS_PER_ENGINE,
                inter_op_num_threads=OCR_THREADS_PER_ENGINE,
            )
        return engine

    def release(self, engine: RapidOCR):
        self.pool.put(engine)

# Singleton pool
ocr_pool = RapidsEnginePool()
