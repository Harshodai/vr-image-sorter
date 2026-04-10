# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
Real Image OCR Benchmark
===============================
Tests RapidOCR Pipeline natively on actual saree images from tests/sandbox/.
"""

import os
import time
import gc
import re
import logging
from core.config import ENABLE_BARCODE_SCANNER

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logging.basicConfig(level=logging.ERROR)

# Ground truth VR codes for each sandbox image
GROUND_TRUTH = {
    "test_user_image.jpg": "VR221130",
    "WhatsApp Image 2025-10-13 at 8.18.20 PM (1).jpeg": "VR89056",
    "WhatsApp Image 2025-10-13 at 8.18.20 PM.jpeg": "VR90803",
    "WhatsApp Image 2025-10-13 at 8.18.21 PM (1).jpeg": "VR86979",
    "WhatsApp Image 2025-10-13 at 8.18.21 PM.jpeg": "VR88772",
    "WhatsApp Image 2026-02-22 at 12.27.29 PM.jpeg": "VR221130",
    "WhatsApp Image 2026-02-22 at 12.27.29 PM copy.jpeg": "VR221130",
    "WhatsApp Image 2026-03-04 at 7.09.25 PM.jpeg": "VR164603",
    "WhatsApp Image 2026-03-04 at 7.09.58 PM.jpeg": "VR216168",
    "WhatsApp Image 2026-03-04 at 7.11.01 PM.jpeg": "VR226959",
    "WhatsApp Image 2026-03-04 at 7.11.33 PM.jpeg": "VR226941",
}

SANDBOX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "sandbox")

def get_memory_mb():
    if not HAS_PSUTIL: return 0.0
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)

def run_tests():
    print("\n" + "=" * 70)
    print("  TESTING VR SAREE SORTER PIPELINE")
    print("=" * 70)

    # Initialize pool
    from scanner.engine_pool import ocr_pool
    from scanner.pipeline import process_pipeline
    from scanner.utils import standardize_filename
    
    mem_before = get_memory_mb()
    ocr_pool.initialize()
    mem_after_load = get_memory_mb()
    
    print(f"  RapidOCR pool initialized: {mem_before:.0f}MB -> {mem_after_load:.0f}MB")
    print(f"\n  {'File':<42} {'Expected':<12} {'Got':<12} {'Match':<6} {'Time':>8}")
    print(f"  {'-'*42} {'-'*12} {'-'*12} {'-'*6} {'-'*8}")

    total_time = 0
    passed = 0
    results = []

    for filename, expected_vr in GROUND_TRUTH.items():
        filepath = os.path.join(SANDBOX_DIR, filename)
        if not os.path.exists(filepath):
            continue

        with open(filepath, "rb") as f:
            image_bytes = f.read()

        t_start = time.time()
        result = process_pipeline(image_bytes)
        t_scan = time.time() - t_start
        total_time += t_scan

        standardized = standardize_filename(result) if result else None
        match = standardized == expected_vr

        if match: passed += 1
        
        icon = "PASS" if match else "FAIL"
        got = standardized or "--"
        print(f"  {filename[:40]:<42} {expected_vr:<12} {got:<12} {icon:<6} {t_scan:>7.2f}s")
        
        results.append({"file": filename, "expected": expected_vr, "got": got, "match": match})
        gc.collect()

    mem_after = get_memory_mb()
    total = len(results)
    accuracy = (passed / total * 100) if total > 0 else 0

    print(f"\n  Pipeline Accuracy: {accuracy:.0f}% ({passed}/{total})")
    print(f"  Total time: {total_time:.2f}s (avg {total_time/max(total,1):.2f}s/image)")
    print(f"  Final Memory: {mem_after:.0f}MB")

    if accuracy == 100:
        print("\n  >>> 100% ACCURACY ACHIEVED! <<<")
    else:
        print("\n  FAILURES:")
        for r in [r for r in results if not r["match"]]:
            print(f"    - {r['file']}: expected {r['expected']}, got {r['got']}")

if __name__ == "__main__":
    run_tests()
