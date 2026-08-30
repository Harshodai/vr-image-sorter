import os
import sys
import time
import gc
from scanner.pipeline import process_pipeline
from scanner.utils import standardize_filename
from scanner.engine_pool import ocr_pool

def run_varahi_benchmark():
    test_dirs = [
        os.path.join(os.path.dirname(__file__), "tests", "varahitesting"),
        "/data/varahitesting",
        "/Users/harshodaikolluru/varahitesting",
    ]
    target_dir = None
    for d in test_dirs:
        if os.path.exists(d) and os.path.isdir(d):
            target_dir = d
            break

    if not target_dir:
        print("Error: varahitesting directory not found in candidate paths.")
        sys.exit(1)

    images = sorted([
        f for f in os.listdir(target_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    ])

    if not images:
        print(f"No images found in {target_dir}")
        sys.exit(1)

    print("\n" + "=" * 90)
    print(f"  VARAHI DATASET BENCHMARK: {len(images)} PRODUCTION SAREE IMAGES")
    print(f"  Source: {target_dir}")
    print("=" * 90)

    ocr_pool.initialize()

    results = []
    t_total_start = time.time()

    for i, filename in enumerate(images, 1):
        filepath = os.path.join(target_dir, filename)
        t_start = time.time()
        try:
            with open(filepath, "rb") as f:
                image_bytes = f.read()

            res = process_pipeline(image_bytes)
            t_elapsed = time.time() - t_start

            code_str = standardize_filename(res.code) if res.code else "--"

            if res.code and res.is_confident:
                status = "CONFIDENT"
            elif res.code and res.needs_review:
                status = "REVIEW"
            else:
                status = "FAILED"

            results.append({
                "file": filename,
                "code": code_str,
                "confidence": res.confidence,
                "method": res.method,
                "status": status,
                "reason": res.reason,
                "time": t_elapsed
            })

            print(f"[{i:3d}/{len(images):3d}] {filename[:38]:<40} -> {code_str:<10} ({status:<9}) {t_elapsed:>5.2f}s  [{res.method}] {res.reason}")
        except Exception as e:
            t_elapsed = time.time() - t_start
            status = "FAILED"
            reason = f"Exception: {e}"
            results.append({
                "file": filename,
                "code": "--",
                "confidence": 0.0,
                "method": "error",
                "status": status,
                "reason": reason,
                "time": t_elapsed
            })
            print(f"[{i:3d}/{len(images):3d}] {filename[:38]:<40} -> {'--':<10} ({status:<9}) {t_elapsed:>5.2f}s  [error] {reason}")

    total_elapsed = time.time() - t_total_start
    confident_count = sum(1 for r in results if r["status"] == "CONFIDENT")
    review_count = sum(1 for r in results if r["status"] == "REVIEW")
    failed_count = sum(1 for r in results if r["status"] == "FAILED")
    avg_time = total_elapsed / len(images) if images else 0

    print("\n" + "=" * 90)
    print("  BENCHMARK SUMMARY RESULTS")
    print("=" * 90)
    print(f"  Total Images Processed : {len(images)}")
    print(f"  Confident Auto-Renamed : {confident_count}/{len(images)} ({confident_count/len(images)*100:.1f}%)")
    print(f"  Routed to Review       : {review_count}/{len(images)} ({review_count/len(images)*100:.1f}%)")
    print(f"  Failed / Unreadable    : {failed_count}/{len(images)} ({failed_count/len(images)*100:.1f}%)")
    print(f"  Total Batch Time       : {total_elapsed:.2f}s")
    print(f"  Average Time / Image   : {avg_time:.2f}s")
    print(f"  Throughput             : {len(images)/total_elapsed:.2f} images/second")
    print("=" * 90)

    if confident_count == len(images):
        print("\n  >>> 100% CONFIDENCE COVERAGE ACHIEVED ON VARAHI BENCHMARK! <<<\n")

if __name__ == "__main__":
    run_varahi_benchmark()
