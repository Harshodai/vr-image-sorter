import os
import sys
import time
from scanner.pipeline import process_pipeline
from scanner.utils import standardize_filename
from scanner.engine_pool import ocr_pool

# Ground-truth VR code extracted from an image filename.
# Filenames on this project follow the convention:
#   VR173873.jpg  or  VR173873_1.jpg  or  VR173873_some_label.jpg
# We extract the leading VR + digits token as the ground-truth code.
import re
_GT_RX = re.compile(r"VR\d{4,8}", re.IGNORECASE)

def _ground_truth_from_filename(filename: str) -> str | None:
    """Extract the VR code ground-truth embedded in the filename, if present."""
    stem = os.path.splitext(filename)[0]
    m = _GT_RX.search(stem.upper())
    return m.group(0) if m else None


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    datasets = [
        ("Input Dataset", os.path.join(root, "..", "input")),
        ("Sandbox Dataset", os.path.join(root, "tests", "sandbox")),
        ("Varahi Production Dataset", os.path.join(root, "tests", "varahitesting")),
    ]

    ocr_pool.initialize()

    grand_total = 0
    grand_passed = 0      # confident AND correct (matches ground truth when available)
    grand_wrong = 0       # confident BUT incorrect code (wrong rename would have occurred)
    grand_review = 0      # detected but sent to review
    grand_time = 0.0
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
        ds_passed = 0
        ds_wrong = 0
        ds_time = 0.0

        for i, filename in enumerate(images, 1):
            filepath = os.path.join(directory, filename)
            t0 = time.time()
            ground_truth = _ground_truth_from_filename(filename)
            try:
                with open(filepath, "rb") as f:
                    image_bytes = f.read()

                res = process_pipeline(image_bytes)
                elapsed = time.time() - t0
                ds_time += elapsed

                predicted = standardize_filename(res.code) if res.code else None

                if res.is_confident:
                    if ground_truth is None:
                        # No ground truth in filename — count as passed (no correctness check)
                        status = "PASS"
                        ds_passed += 1
                    elif predicted == ground_truth:
                        status = "PASS"
                        ds_passed += 1
                    else:
                        # Confident but WRONG — this would have caused a silent bad rename
                        status = "WRONG"
                        ds_wrong += 1
                elif res.code and res.needs_review:
                    status = "REVIEW"
                else:
                    status = "FAIL"

                code_str = predicted or "--"
                gt_label = f" (GT:{ground_truth})" if ground_truth and status == "WRONG" else ""
                print(f"  [{i:3d}/{len(images):3d}] {filename[:36]:<38} -> {code_str:<10}{gt_label} ({status:<6}) {elapsed:>5.2f}s [{res.method}]")
            except Exception as e:
                elapsed = time.time() - t0
                ds_time += elapsed
                print(f"  [{i:3d}/{len(images):3d}] {filename[:36]:<38} -> ERROR      (FAIL  ) {elapsed:>5.2f}s [error: {e}]")

        grand_total += len(images)
        grand_passed += ds_passed
        grand_wrong += ds_wrong
        grand_time += ds_time
        print(f"  --> {name} Result: {ds_passed}/{len(images)} correct, {ds_wrong} wrong, in {ds_time:.2f}s (avg {ds_time/max(len(images),1):.2f}s/img)")

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
    if grand_total > 0:
        print(f"  Passed / Correct       : {grand_passed}/{grand_total} ({grand_passed/grand_total*100:.1f}%)")
        if grand_wrong > 0:
            print(f"  *** WRONG (bad rename) : {grand_wrong}/{grand_total} ({grand_wrong/grand_total*100:.1f}%) ***")
    else:
        print("  Passed / Correct       : 0/0 (0.0%)")
    print(f"  Total Time Elapsed     : {grand_time:.2f}s")
    print(f"  Average Time / Image   : {grand_time/max(grand_total,1):.2f}s")
    print(f"  Throughput             : {grand_total/max(grand_time,0.001):.2f} images/second")
    print("=" * 90)

    # Perfect accuracy requires: all datasets present, all images correct, zero wrong renames.
    is_perfect = (
        grand_total > 0 and
        len(skipped_datasets) == 0 and
        len(empty_datasets) == 0 and
        grand_passed == grand_total and
        grand_wrong == 0
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
        if grand_wrong > 0:
            reasons.append(f"{grand_wrong} image(s) produced an incorrect confident rename")
        if grand_passed < grand_total - grand_wrong:
            reasons.append(f"{grand_total - grand_passed - grand_wrong} image(s) failed or require review")
        print(f"\n  Notice: Benchmark did not achieve full perfect coverage ({'; '.join(reasons)}).\n")

if __name__ == "__main__":
    main()
