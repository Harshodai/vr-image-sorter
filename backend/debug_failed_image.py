import os
import sys
import io
import time
import logging
import cv2

# Fix unicode characters crashing windows terminals
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Route backend modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner.engine_pool import ocr_pool
from scanner.pipeline import process_pipeline
from core.logger import logger

logger.setLevel(logging.DEBUG)

def debug_image(filename: str):
    filepath = os.path.join(r"C:\Users\khars\PycharmProjects\vr-image-sorter\tests\sandbox", filename)
    
    if not os.path.exists(filepath):
        print(f"Error: Could not find '{filepath}'")
        return

    print(f"Scanning image: {filepath}")
    print("-" * 60)

    # Initialize pooling to mimic pipeline state
    ocr_pool.initialize()

    with open(filepath, "rb") as f:
        image_bytes = f.read()

    # Track time and execution
    t_start = time.time()
    
    # Process through exact production pipeline (with logging turned up to DEBUG)
    result = process_pipeline(image_bytes)
    
    t_end = time.time()
    print(f"\n--> Final Output: {result}")
    print(f"--> Extracted in: {t_end - t_start:.2f}s")


if __name__ == "__main__":
    # You can target any exact failing image here:
    target_image = "test_user_image.jpg"
    debug_image(target_image)
