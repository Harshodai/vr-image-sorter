"""
Test script: runs the full pipeline (zxing-cpp barcode + RapidOCR fallback)
against every image in the ./input folder using the actual backend pipeline.

Run from the repo root:
    python3 test_pipeline.py
"""

import sys
import os
import time

# Add backend to path so imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

INPUT_DIR = os.path.join(os.path.dirname(__file__), "input")

# Expected VR codes from visual inspection of the 7 production images
EXPECTED = {
    "WhatsApp Image 2025-10-13 at 20.18.20 (1).jpeg": "VR90803",
    "WhatsApp Image 2025-10-13 at 20.18.20 (2).jpeg": "VR89056",
    "WhatsApp Image 2025-10-13 at 20.18.20.jpeg": "VR89056",
    "WhatsApp Image 2025-10-13 at 20.18.21 (1).jpeg": "VR86979",
    "WhatsApp Image 2025-10-13 at 20.18.21 (2).jpeg": "VR88772",
    "WhatsApp Image 2025-10-13 at 20.18.21 (3).jpeg": "VR86979",
    "WhatsApp Image 2025-10-13 at 20.18.21.jpeg": "VR88772",
}

def main():
    from scanner.pipeline import process_pipeline

    images = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
    if not images:
        print("No images found in ./input/")
        return

    print(f"\nTesting {len(images)} production images")
    print(f"{'='*70}")
    correct, wrong, failed, review = 0, 0, 0, 0

    for fname in sorted(images):
        path = os.path.join(INPUT_DIR, fname)
        with open(path, "rb") as f:
            image_bytes = f.read()

        t0 = time.monotonic()
        result = process_pipeline(image_bytes)
        elapsed = time.monotonic() - t0

        expected = EXPECTED.get(fname, "???")
        short_name = fname[:44]
        conf = f"{result.confidence:.3f}"

        if result.code is None:
            print(f"  FAILED   {short_name:44s} expected={expected}  ({elapsed:.2f}s) {result.reason}")
            failed += 1
        elif result.needs_review:
            flag = "OK" if result.code == expected else "WRONG"
            print(f"  REVIEW   {short_name:44s} -> {result.code} [{flag}] conf={conf} ({elapsed:.2f}s) {result.reason}")
            review += 1
        elif result.code == expected:
            print(f"  CORRECT  {short_name:44s} -> {result.code} conf={conf} via {result.method} ({elapsed:.2f}s)")
            correct += 1
        else:
            print(f"  WRONG    {short_name:44s} -> {result.code} (expected {expected}) conf={conf} ({elapsed:.2f}s)")
            wrong += 1

    total = correct + wrong + failed + review
    print(f"\n{'='*70}")
    print(f"Results: {correct}/{total} auto-renamed correctly, {wrong} WRONG, "
          f"{review} sent to review, {failed} failed")
    if wrong:
        print(f"*** {wrong} silently wrong rename(s) — this is the failure that matters ***")
    elif correct == total:
        print("100% auto-renamed, zero review needed")
    else:
        print(f"Zero wrong renames. Auto-renamed {round(correct/total*100)}%, "
              f"remaining {review + failed} need a human.")

if __name__ == "__main__":
    main()
