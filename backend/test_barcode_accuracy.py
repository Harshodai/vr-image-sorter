"""
Diagnostic run over the test images, with the intermediate label crops written
to disk so you can see what the detector actually handed to the OCR engine.

    python test_barcode_accuracy.py

Writes debug crops and an annotated overlay to tests/debug_output/.
Use this when a specific image misbehaves; use test_real_images.py for the
plain pass/fail accuracy number.
"""
import glob
import logging
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

os.environ.setdefault("ENABLE_BARCODE_SCANNER", "True")

from scanner.pipeline import process_pipeline  # noqa: E402
from scanner.utils import detect_label_regions, standardize_filename  # noqa: E402

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_DIR = os.path.join(BASE_DIR, "tests", "debug_output")


def test_single_image(image_path, expected=None):
    print(f"\n{'=' * 70}")
    print(f"  Testing: {os.path.basename(image_path)}")
    print(f"  Expected: {expected or 'Unknown'}")
    print(f"{'=' * 70}")

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    image = cv2.imread(image_path)
    if image is None:
        print(f"  ERROR: could not load image: {image_path}")
        return None, 0

    os.makedirs(DEBUG_DIR, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(image_path))[0]

    # Show what the label detector produced, using the same function the
    # pipeline uses rather than a re-implementation that can drift from it.
    label_crops = detect_label_regions(image)
    print(f"\n  Label regions detected: {len(label_crops)}")
    for i, crop in enumerate(label_crops):
        crop_path = os.path.join(DEBUG_DIR, f"{base_name}_label_crop_{i}.png")
        cv2.imwrite(crop_path, crop)
        h, w = crop.shape[:2]
        print(f"     Crop {i}: {w}x{h}px -> {crop_path}")

    start_time = time.monotonic()
    result = process_pipeline(image_bytes)
    elapsed = time.monotonic() - start_time

    if result.code:
        standardized = standardize_filename(result.code)
        if not result.is_confident:
            status = "REVIEW"
        elif expected and expected in standardized:
            status = "PASS"
        elif expected:
            status = "WRONG"
        else:
            status = "RESULT"
        print(f"\n  {status}: {standardized}  (confidence {result.confidence:.3f} "
              f"via {result.method})")
        print(f"  Reason: {result.reason}")
        if expected and expected not in standardized:
            print(f"  Expected '{expected}' but got '{standardized}'")
    else:
        print(f"\n  FAIL: no VR code detected ({result.reason})")
    print(f"  Time: {elapsed:.2f}s")

    return result, elapsed


def main():
    test_images = []
    sandbox = os.path.join(BASE_DIR, "tests", "sandbox")

    user_img = os.path.join(sandbox, "test_user_image.jpg")
    if os.path.exists(user_img):
        test_images.append((user_img, "VR221130"))

    for f in sorted(glob.glob(os.path.join(sandbox, "WhatsApp*.jpeg"))):
        test_images.append((f, None))

    if not test_images:
        print(f"No test images found under {sandbox}")
        return 1

    total_time = 0.0
    passed = wrong = review = failed = 0
    for path, expected in test_images:
        result, elapsed = test_single_image(path, expected)
        total_time += elapsed
        if result is None or not result.code:
            failed += 1
        elif not result.is_confident:
            review += 1
        elif expected and expected not in standardize_filename(result.code):
            wrong += 1
        else:
            passed += 1

    n = len(test_images)
    print(f"\n{'=' * 70}")
    print(f"  {n} image(s) in {total_time:.1f}s (avg {total_time / n:.2f}s)")
    print(f"  auto-renamed={passed}  wrong={wrong}  review={review}  unreadable={failed}")
    print(f"  Debug output: {DEBUG_DIR}")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
