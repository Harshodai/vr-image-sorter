import os
import sys
import time
from scanner.pipeline import process_pipeline
from scanner.utils import standardize_filename
from scanner.engine_pool import ocr_pool

def main():
    root = os.path.dirname(os.path.abspath(__file__))
    datasets = [
        ("Input Dataset", os.path.join(root, "..", "input")),
        ("Sandbox Dataset", os.path.join(root, "tests", "sandbox")),
        ("Varahi Production Dataset", os.path.join(root, "tests", "varahitesting")),
    ]

    ocr_pool.initialize()

    grand_total = 0
    grand_passed = 0
    grand_time = 0.0
    all_results = []
    skipped_datasets = []
    empty_datasets = []
    processed_datasets = []

    print("\n" + "=" * 90)
    print("  RUNNING MASTER BENCHMARK ACROSS ALL DATASETS (124+ IMAGES)")
    print("=" * 90)

    for name, directory in datasets:
        if not os.path.exists(directory):
            print(f"\n--- Skipping {name}: directory {directory} not found ---")
            skipped_datasets.append(f"{name} (missing: {directory})")
            continue

        images = sorted([
            f for f in os.listdir(directory)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        ])

        if not images:
            print(f"\n--- Skipping {name}: 0 images found in {directory} ---")
            empty_datasets.append(f"{name} (empty: {directory})")
            continue

        processed_datasets.append(name)
        print(f"\n--- {name}: {len(images)} images in {directory} ---")
        passed = 0
        ds_time = 0.0

        for i, filename in enumerate(images, 1):
            filepath = os.path.join(directory, filename)
            t0 = time.time()
            try:
                with open(filepath, "rb") as f:
                    image_bytes = f.read()

                res = process_pipeline(image_bytes)
                elapsed = time.time() - t0
                ds_time += elapsed

                code_str = standardize_filename(res.code) if res.code else "--"

                if res.code and res.is_confident:
                    status = "PASS"
                    passed += 1
                elif res.code and res.needs_review:
                    status = "REVIEW"
                else:
                    status = "FAIL"

                print(f"  [{i:3d}/{len(images):3d}] {filename[:38]:<40} -> {code_str:<10} ({status:<6}) {elapsed:>5.2f}s [{res.method}]")
            except Exception as e:
                elapsed = time.time() - t0
                ds_time += elapsed
                status = "FAIL"
                print(f"  [{i:3d}/{len(images):3d}] {filename[:38]:<40} -> ERROR      ({status:<6}) {elapsed:>5.2f}s [error: {e}]")

        grand_total += len(images)
        grand_passed += passed
        grand_time += ds_time
        print(f"  --> {name} Result: {passed}/{len(images)} passed in {ds_time:.2f}s (avg {ds_time/max(len(images),1):.2f}s/img)")

    print("\n" + "=" * 90)
    print("  GRAND MASTER BENCHMARK SUMMARY")
    print("=" * 90)
    print(f"  Datasets Configured    : {len(datasets)}")
    print(f"  Datasets Processed     : {len(processed_datasets)}/{len(datasets)}")
    if skipped_datasets:
        print(f"  Datasets Missing       : {len(skipped_datasets)} -> {', '.join(skipped_datasets)}")
    if empty_datasets:
        print(f"  Datasets Empty         : {len(empty_datasets)} -> {', '.join(empty_datasets)}")
    print(f"  Total Images Tested    : {grand_total}")
    print(f"  Passed / Auto-Renamed  : {grand_passed}/{grand_total} ({grand_passed/max(grand_total,1)*100:.1f}%)" if grand_total > 0 else "  Passed / Auto-Renamed  : 0/0 (0.0%)")
    print(f"  Total Time Elapsed     : {grand_time:.2f}s")
    print(f"  Average Time / Image   : {grand_time/max(grand_total,1):.2f}s")
    print(f"  Throughput             : {grand_total/max(grand_time,0.001):.2f} images/second")
    print("=" * 90)

    is_perfect = (
        grand_total > 0 and
        len(skipped_datasets) == 0 and
        len(empty_datasets) == 0 and
        grand_passed == grand_total
    )

    if is_perfect:
        print(f"\n  >>> 100% PERFECT ACCURACY ACROSS ALL {len(datasets)} DATASETS ({grand_passed}/{grand_total})! <<<\n")
    else:
        reasons = []
        if grand_total == 0:
            reasons.append("0 images processed")
        if skipped_datasets:
            reasons.append(f"{len(skipped_datasets)} dataset(s) missing")
        if empty_datasets:
            reasons.append(f"{len(empty_datasets)} dataset(s) empty")
        if grand_passed < grand_total:
            reasons.append(f"{grand_total - grand_passed} image(s) failed or require review")
        print(f"\n  Notice: Benchmark did not achieve full perfect coverage ({'; '.join(reasons)}).\n")

if __name__ == "__main__":
    main()
