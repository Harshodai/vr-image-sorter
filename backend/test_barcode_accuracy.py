"""
Standalone test script to verify barcode/OCR detection accuracy.
Tests the enhanced SareeSorter against all available test images.

Usage:
    python test_barcode_accuracy.py

Expected results:
    - Green pattu saree (user image) -> VR221130
    - test_image_0.jpg (fancy saree)  -> VR90803
"""

import cv2
import numpy as np
import os
import sys
import time
import glob
import logging

# Enable debug logging to see the detection pipeline steps
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Import the SareeSorter from main.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force barcode scanner ON for testing
os.environ["ENABLE_BARCODE_SCANNER"] = "True"
from main import SareeSorter


def test_single_image(sorter, image_path, expected=None):
    """Test a single image and return results."""
    print(f"\n{'='*70}")
    print(f"  Testing: {os.path.basename(image_path)}")
    print(f"  Expected: {expected or 'Unknown'}")
    print(f"{'='*70}")

    # Read image bytes (same as the API does)
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    
    # Also load as cv2 for debug visualization
    image = cv2.imread(image_path)
    if image is None:
        print(f"  ❌ ERROR: Could not load image: {image_path}")
        return None, 0

    # Step 1: Show label detection results
    label_crops = sorter.detect_label_regions(image)
    print(f"\n  📋 Label regions detected: {len(label_crops)}")
    
    # Save debug crops
    debug_dir = os.path.join(os.path.dirname(image_path), "..", "debug_output")
    os.makedirs(debug_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    
    for i, crop in enumerate(label_crops):
        crop_path = os.path.join(debug_dir, f"{base_name}_label_crop_{i}.png")
        cv2.imwrite(crop_path, crop)
        h, w = crop.shape[:2]
        print(f"     Crop {i}: {w}x{h}px -> saved to {crop_path}")
    
    # Save annotated full image showing detected regions
    annotated = image.copy()
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, np.array([0, 0, 170]), np.array([180, 50, 255]))
    mask2 = cv2.inRange(hsv, np.array([0, 0, 150]), np.array([180, 70, 255]))
    mask = cv2.bitwise_or(mask1, mask2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_small)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    img_area = image.shape[0] * image.shape[1]
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if img_area * 0.005 < area < img_area * 0.3:
            rect = cv2.minAreaRect(cnt)
            box = cv2.boxPoints(rect)
            box = np.intp(box)
            cv2.drawContours(annotated, [box], 0, (0, 255, 0), 3)
    
    annotated_path = os.path.join(debug_dir, f"{base_name}_annotated.png")
    cv2.imwrite(annotated_path, annotated)
    print(f"     Annotated image -> {annotated_path}")
    
    # Step 2: Run full pipeline
    start_time = time.time()
    result = sorter.scan_barcode_from_bytes(image_bytes)
    elapsed = time.time() - start_time
    
    # Step 3: Report
    if result:
        standardized = sorter.standardize_filename(result)
        status = "✅ PASS" if (expected and expected in standardized) else "⚠️  RESULT"
        print(f"\n  {status}: {standardized}")
        print(f"  ⏱  Time: {elapsed:.2f}s")
        
        if expected and expected not in standardized:
            print(f"  ⚠️  Expected '{expected}' but got '{standardized}'")
    else:
        print(f"\n  ❌ FAIL: No barcode/VR code detected")
        print(f"  ⏱  Time: {elapsed:.2f}s")
    
    return result, elapsed


def main():
    sorter = SareeSorter()
    
    # Collect all test images
    test_images = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # User's specific test image
    user_img = os.path.join(base_dir, "tests", "sandbox", "test_user_image.jpg")
    if os.path.exists(user_img):
        test_images.append((user_img, "VR221130"))
    
    # Also check the sandbox WhatsApp image (same image potentially)
    for f in glob.glob(os.path.join(base_dir, "tests", "sandbox", "WhatsApp*.jpeg")):
        test_images.append((f, None))
    
    # Test fixtures
    for f in sorted(glob.glob(os.path.join(base_dir, "tests", "fixtures", "*.jpg"))):
        expected = None
        basename = os.path.basename(f)
        if basename == "test_image_0.jpg":
            expected = "VR90803"
        test_images.append((f, expected))
    
    # Run all tests
    print("\n" + "="*70)
    print("  BARCODE/OCR ACCURACY TEST SUITE")
    print("  Enhanced Label-First Detection Pipeline")
    print("="*70)
    print(f"  Total images to test: {len(test_images)}")
    
    results = []
    total_start = time.time()
    
    for image_path, expected in test_images:
        result, elapsed = test_single_image(sorter, image_path, expected)
        results.append({
            "file": os.path.basename(image_path),
            "result": result,
            "expected": expected,
            "time": elapsed,
            "pass": result is not None
        })
    
    total_time = time.time() - total_start
    
    # Summary table
    print("\n\n" + "="*70)
    print("  RESULTS SUMMARY")
    print("="*70)
    print(f"  {'File':<45} {'Result':<15} {'Time':>8}")
    print(f"  {'-'*45} {'-'*15} {'-'*8}")
    
    passed = 0
    for r in results:
        result_str = r['result'] or "FAILED"
        status_icon = "✅" if r['pass'] else "❌"
        print(f"  {status_icon} {r['file']:<43} {result_str:<15} {r['time']:>6.2f}s")
        if r['pass']:
            passed += 1
    
    print(f"\n  Total: {passed}/{len(results)} detected | Total time: {total_time:.2f}s")
    print(f"  Debug images saved to: tests/debug_output/")
    print("="*70)


if __name__ == "__main__":
    main()
