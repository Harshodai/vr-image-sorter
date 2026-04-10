# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
"""
OCR Engine Comparison Test
==========================
Tests EasyOCR vs RapidOCR vs Tesseract for VR code detection.
Measures: accuracy, speed, and memory usage.

Usage:
    # First install the test dependencies:
    pip install rapidocr-onnxruntime pytesseract psutil

    # (Tesseract also needs the system binary installed)
    # Windows: choco install tesseract  OR  download from https://github.com/UB-Mannheim/tesseract/wiki
    # Linux:   apt-get install tesseract-ocr

    python test_ocr_comparison.py
"""

import os
import time
import gc
import re
import logging
import cv2
import numpy as np

# Attempt to import psutil for memory tracking
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("WARNING: psutil not installed. Memory tracking disabled.")
    print("  Install with: pip install psutil")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def get_memory_mb():
    """Get current process RSS in MB."""
    if not HAS_PSUTIL:
        return 0.0
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def create_test_images():
    """Create synthetic test images with known VR codes."""
    test_cases = []
    
    # Test 1: Clean black text on white background (ideal case)
    img1 = np.ones((200, 500, 3), dtype=np.uint8) * 255
    cv2.putText(img1, "VR221130", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 0, 0), 4, cv2.LINE_AA)
    test_cases.append(("clean_large", img1, "VR221130"))
    
    # Test 2: Smaller text (simulating a label crop)
    img2 = np.ones((100, 300, 3), dtype=np.uint8) * 255
    cv2.putText(img2, "VR90803", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3, cv2.LINE_AA)
    test_cases.append(("clean_small", img2, "VR90803"))
    
    # Test 3: Text with noise (simulating real-world label)
    img3 = np.ones((200, 500, 3), dtype=np.uint8) * 240  # slightly off-white
    cv2.putText(img3, "VR154027", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (20, 20, 20), 3, cv2.LINE_AA)
    # Add some noise
    noise = np.random.randint(0, 30, img3.shape, dtype=np.uint8)
    img3 = cv2.subtract(img3, noise)
    test_cases.append(("noisy", img3, "VR154027"))
    
    # Test 4: Multi-line label (VR code + other text like MRP)
    img4 = np.ones((300, 500, 3), dtype=np.uint8) * 255
    cv2.putText(img4, "VR221130", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img4, "MRP: 2500", (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(img4, "Size: Free", (30, 230), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
    test_cases.append(("multi_line", img4, "VR221130"))
    
    # Test 5: Rotated 180 degrees (upside-down label)
    img5 = np.ones((200, 500, 3), dtype=np.uint8) * 255
    cv2.putText(img5, "VR331455", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 3, cv2.LINE_AA)
    img5 = cv2.rotate(img5, cv2.ROTATE_180)
    test_cases.append(("rotated_180", img5, "VR331455"))
    
    # Test 6: Low contrast
    img6 = np.ones((200, 500, 3), dtype=np.uint8) * 200
    cv2.putText(img6, "VR567890", (30, 130), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (100, 100, 100), 3, cv2.LINE_AA)
    test_cases.append(("low_contrast", img6, "VR567890"))
    
    return test_cases


def extract_vr_code(text):
    """Extract VR code from OCR text using the same logic as main.py."""
    clean = text.replace(" ", "").upper()
    # Fix common OCR confusions
    ocr_digit_map = str.maketrans("OoIl|", "00111")
    clean = clean.translate(ocr_digit_map)
    clean = re.sub(r"[^A-Z0-9]", "", clean)
    
    if "VR" in clean:
        match = re.search(r"VR\d{2,8}(?!\d)", clean)
        if match:
            return match.group(0)
    return None


# ── Engine 1: EasyOCR ─────────────────────────────────────────────────
def test_easyocr(test_cases):
    """Test EasyOCR engine."""
    print("\n" + "="*60)
    print("  ENGINE 1: EasyOCR (current)")
    print("="*60)
    
    try:
        import easyocr
    except ImportError:
        print("  [WARN] easyocr not installed -- skipping")
        return None
    
    gc.collect()
    mem_before = get_memory_mb()
    
    t_load_start = time.time()
    reader = easyocr.Reader(['en'], gpu=False, verbose=False)
    t_load = time.time() - t_load_start
    
    mem_after_load = get_memory_mb()
    print(f"  Model load time: {t_load:.2f}s")
    print(f"  Memory: {mem_before:.0f}MB -> {mem_after_load:.0f}MB (delta {mem_after_load - mem_before:.0f}MB)")
    
    results = []
    total_time = 0
    
    for name, image, expected in test_cases:
        t_start = time.time()
        ocr_results = reader.readtext(image)
        t_scan = time.time() - t_start
        total_time += t_scan
        
        # Extract VR code from all detected text
        all_text = " ".join([text for _, text, _ in ocr_results])
        vr_code = extract_vr_code(all_text)
        
        match = vr_code == expected if vr_code else False
        results.append({
            "name": name, "expected": expected, "got": vr_code,
            "match": match, "time": t_scan, "raw": all_text
        })
    
    mem_after_scan = get_memory_mb()
    
    # Print results
    _print_results(results, total_time, mem_before, mem_after_load, mem_after_scan, t_load)
    
    # Cleanup
    del reader
    gc.collect()
    
    return {
        "engine": "EasyOCR",
        "load_time": t_load,
        "mem_delta_load": mem_after_load - mem_before,
        "mem_after_scan": mem_after_scan,
        "results": results,
        "total_scan_time": total_time,
        "accuracy": sum(1 for r in results if r["match"]) / len(results)
    }


# ── Engine 2: RapidOCR ────────────────────────────────────────────────
def test_rapidocr(test_cases):
    """Test RapidOCR engine."""
    print("\n" + "="*60)
    print("  ENGINE 2: RapidOCR (ONNX Runtime)")
    print("="*60)
    
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print("  [WARN] rapidocr-onnxruntime not installed -- skipping")
        print("  Install with: pip install rapidocr-onnxruntime")
        return None
    
    gc.collect()
    mem_before = get_memory_mb()
    
    t_load_start = time.time()
    engine = RapidOCR()
    t_load = time.time() - t_load_start
    
    mem_after_load = get_memory_mb()
    print(f"  Model load time: {t_load:.2f}s")
    print(f"  Memory: {mem_before:.0f}MB -> {mem_after_load:.0f}MB (delta {mem_after_load - mem_before:.0f}MB)")
    
    results = []
    total_time = 0
    
    for name, image, expected in test_cases:
        t_start = time.time()
        ocr_result, _ = engine(image)
        t_scan = time.time() - t_start
        total_time += t_scan
        
        # Extract VR code from results
        all_text = ""
        if ocr_result:
            all_text = " ".join([line[1] for line in ocr_result])
        vr_code = extract_vr_code(all_text)
        
        match = vr_code == expected if vr_code else False
        results.append({
            "name": name, "expected": expected, "got": vr_code,
            "match": match, "time": t_scan, "raw": all_text
        })
    
    mem_after_scan = get_memory_mb()
    _print_results(results, total_time, mem_before, mem_after_load, mem_after_scan, t_load)
    
    del engine
    gc.collect()
    
    return {
        "engine": "RapidOCR",
        "load_time": t_load,
        "mem_delta_load": mem_after_load - mem_before,
        "mem_after_scan": mem_after_scan,
        "results": results,
        "total_scan_time": total_time,
        "accuracy": sum(1 for r in results if r["match"]) / len(results)
    }


# ── Engine 3: Tesseract ───────────────────────────────────────────────
def test_tesseract(test_cases):
    """Test Tesseract OCR engine."""
    print("\n" + "="*60)
    print("  ENGINE 3: Tesseract (pytesseract)")
    print("="*60)
    
    try:
        import pytesseract
    except ImportError:
        print("  [WARN] pytesseract not installed -- skipping")
        print("  Install with: pip install pytesseract")
        print("  Also needs Tesseract binary: choco install tesseract")
        return None
    
    # Verify tesseract binary is accessible
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        print("  [WARN] Tesseract binary not found in PATH -- skipping")
        print("  Install: choco install tesseract  OR  download from:")
        print("    https://github.com/UB-Mannheim/tesseract/wiki")
        return None
    
    gc.collect()
    mem_before = get_memory_mb()
    
    # Tesseract has no model-loading step; it loads per-call
    t_load = 0.0  # No persistent model to load
    mem_after_load = mem_before
    print(f"  Model load time: N/A (loads per-call)")
    print(f"  Memory: {mem_before:.0f}MB (no persistent model)")
    
    results = []
    total_time = 0
    
    for name, image, expected in test_cases:
        # Preprocess: convert to grayscale + Otsu threshold (critical for Tesseract)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        t_start = time.time()
        # PSM 6 = uniform block of text; whitelist VR-relevant chars
        config = r'--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:'
        raw_text = pytesseract.image_to_string(thresh, config=config)
        t_scan = time.time() - t_start
        total_time += t_scan
        
        vr_code = extract_vr_code(raw_text)
        
        match = vr_code == expected if vr_code else False
        results.append({
            "name": name, "expected": expected, "got": vr_code,
            "match": match, "time": t_scan, "raw": raw_text.strip()
        })
    
    mem_after_scan = get_memory_mb()
    _print_results(results, total_time, mem_before, mem_after_load, mem_after_scan, t_load)
    
    gc.collect()
    
    return {
        "engine": "Tesseract",
        "load_time": t_load,
        "mem_delta_load": 0,
        "mem_after_scan": mem_after_scan,
        "results": results,
        "total_scan_time": total_time,
        "accuracy": sum(1 for r in results if r["match"]) / len(results)
    }


def _print_results(results, total_time, mem_before, mem_after_load, mem_after_scan, load_time):
    """Print formatted results table."""
    print(f"\n  {'Test Case':<20} {'Expected':<12} {'Got':<12} {'Match':<6} {'Time':>8}")
    print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*6} {'-'*8}")
    
    for r in results:
        icon = "PASS" if r["match"] else "FAIL"
        got = r["got"] or "--"
        print(f"  {r['name']:<20} {r['expected']:<12} {got:<12} {icon:<6} {r['time']:>7.3f}s")
        if not r["match"]:
            raw_preview = r["raw"][:50] + "..." if len(r["raw"]) > 50 else r["raw"]
            print(f"  {'':20} raw: {raw_preview}")
    
    accuracy = sum(1 for r in results if r["match"]) / len(results) * 100
    print(f"\n  Accuracy: {accuracy:.0f}% ({sum(1 for r in results if r['match'])}/{len(results)})")
    print(f"  Total scan time: {total_time:.3f}s (avg {total_time/len(results):.3f}s/image)")
    print(f"  Memory after all scans: {mem_after_scan:.0f}MB (delta {mem_after_scan - mem_before:.0f}MB from baseline)")


def _print_comparison(all_results):
    """Print side-by-side comparison of all engines."""
    print("\n\n" + "="*70)
    print("  COMPARISON SUMMARY")
    print("="*70)
    
    valid = [r for r in all_results if r is not None]
    if not valid:
        print("  No engines were tested!")
        return
    
    print(f"\n  {'Metric':<30}", end="")
    for r in valid:
        print(f" {r['engine']:>15}", end="")
    print()
    print(f"  {'-'*30}", end="")
    for _ in valid:
        print(f" {'-'*15}", end="")
    print()
    
    # Accuracy
    print(f"  {'Accuracy':<30}", end="")
    for r in valid:
        print(f" {r['accuracy']*100:>13.0f}%", end="")
    print()
    
    # Model load time
    print(f"  {'Model load time':<30}", end="")
    for r in valid:
        if r['load_time'] > 0:
            print(f" {r['load_time']:>13.2f}s", end="")
        else:
            print(f" {'N/A':>15}", end="")
    print()
    
    # Total scan time
    print(f"  {'Total scan time (6 images)':<30}", end="")
    for r in valid:
        print(f" {r['total_scan_time']:>13.3f}s", end="")
    print()
    
    # Avg per image
    n = len(r['results'])
    print(f"  {'Avg time per image':<30}", end="")
    for r in valid:
        print(f" {r['total_scan_time']/n:>13.3f}s", end="")
    print()
    
    # Memory delta from load
    print(f"  {'Memory delta (model load)':<30}", end="")
    for r in valid:
        print(f" {r['mem_delta_load']:>12.0f}MB", end="")
    print()
    
    # Memory after all scans
    print(f"  {'Memory RSS (after scans)':<30}", end="")
    for r in valid:
        print(f" {r['mem_after_scan']:>12.0f}MB", end="")
    print()
    
    print("\n" + "="*70)
    
    # Recommendation
    best_accuracy = max(valid, key=lambda x: x['accuracy'])
    best_speed = min(valid, key=lambda x: x['total_scan_time'])
    best_memory = min(valid, key=lambda x: x['mem_delta_load']) if any(r['mem_delta_load'] > 0 for r in valid) else valid[0]
    
    print(f"\n  Best accuracy:  {best_accuracy['engine']} ({best_accuracy['accuracy']*100:.0f}%)")
    print(f"  Best speed:     {best_speed['engine']} ({best_speed['total_scan_time']:.3f}s total)")
    print(f"  Best memory:    {best_memory['engine']} (delta {best_memory['mem_delta_load']:.0f}MB)")


def test_with_real_images(test_engines_fn):
    """Also test with any real images found in tests/sandbox/."""
    sandbox_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "sandbox")
    if not os.path.exists(sandbox_dir):
        return []
    
    real_images = []
    for f in os.listdir(sandbox_dir):
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            path = os.path.join(sandbox_dir, f)
            img = cv2.imread(path)
            if img is not None:
                real_images.append((f"real:{f[:15]}", img, "UNKNOWN"))
    
    if real_images:
        print(f"\n  Found {len(real_images)} real test images in tests/sandbox/")
    return real_images


def main():
    print("="*70)
    print("  OCR ENGINE COMPARISON TEST")
    print("  Tests: EasyOCR vs RapidOCR vs Tesseract")
    print("  Metrics: Accuracy, Speed, Memory")
    print("="*70)
    
    print(f"\n  Baseline process memory: {get_memory_mb():.0f}MB")
    
    # Generate test images
    test_cases = create_test_images()
    print(f"  Generated {len(test_cases)} synthetic test images")
    
    # Check for real images
    real_cases = test_with_real_images(None)
    if real_cases:
        print(f"  Note: Real images have unknown expected results (marked UNKNOWN)")
    
    # Run each engine
    all_results = []
    
    result_easyocr = test_easyocr(test_cases)
    all_results.append(result_easyocr)
    
    result_rapidocr = test_rapidocr(test_cases)
    all_results.append(result_rapidocr)
    
    result_tesseract = test_tesseract(test_cases)
    all_results.append(result_tesseract)
    
    # Comparison
    _print_comparison(all_results)
    
    print("\n  NOTE: These are synthetic images. Real-world accuracy may differ.")
    print("  Run test_barcode_accuracy.py with your actual saree images for")
    print("  a definitive accuracy comparison.")
    print("="*70)


if __name__ == "__main__":
    main()
