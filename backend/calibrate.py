"""
Find the confidence threshold that gives zero wrong renames on YOUR images.

The shipped default (OCR_MIN_CONFIDENCE=0.90) was derived from 22 images. That
is enough to show the pipeline works and nowhere near enough to promise an
accuracy rate on 100,000. This script replaces that guess with a measurement.

Give it images whose correct codes you know, two ways:

  1. A CSV with a `file` and `code` column:
         python calibrate.py --csv labelled.csv
  2. A folder where each file is already NAMED for its code (VR12345.jpg):
         python calibrate.py --input ./labelled

It scans each image once, then replays the decision at a range of thresholds
and reports, for each:

    WRONG    renamed to the wrong code   <- must be zero
    AUTO     renamed correctly, no human needed
    REVIEW   a human has to confirm it
    FAILED   nothing readable

Raising the threshold moves images from AUTO to REVIEW. It buys safety with
your operators' time. Pick the lowest threshold with zero WRONG, then add
margin — your 100k backlog will contain photographs worse than your sample.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import ALLOWED_EXTENSIONS, BATCH_CONCURRENCY, OCR_MIN_CONFIDENCE  # noqa: E402
from scanner.engine_pool import ocr_pool  # noqa: E402
from scanner.pipeline import process_pipeline  # noqa: E402
from scanner.utils import standardize_filename  # noqa: E402

CODE_RX = re.compile(r"VR\d{4,8}", re.IGNORECASE)
THRESHOLDS = [0.0, 0.50, 0.70, 0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.98, 0.99, 0.995]


def load_from_csv(path: Path) -> list[tuple[Path, str]]:
    pairs = []
    with path.open() as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        file_col = cols.get("file") or cols.get("filename") or cols.get("path")
        code_col = cols.get("code") or cols.get("expected") or cols.get("vr_code")
        if not file_col or not code_col:
            raise SystemExit(
                f"CSV needs a file column (file/filename/path) and a code column "
                f"(code/expected/vr_code). Found: {reader.fieldnames}"
            )
        base = path.parent
        for row in reader:
            raw = (row.get(file_col) or "").strip()
            code = standardize_filename((row.get(code_col) or "").strip())
            if not raw or not code:
                continue
            img = Path(raw)
            if not img.is_absolute():
                img = base / img
            pairs.append((img, code))
    return pairs


def load_from_folder(root: Path) -> list[tuple[Path, str]]:
    """Filenames are the labels: VR12345.jpg, VR12345_2.jpg, VR12345 (1).jpg."""
    pairs = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        m = CODE_RX.search(p.stem.upper())
        if m:
            pairs.append((p, m.group(0)))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="CSV with `file` and `code` columns")
    src.add_argument("--input", help="folder where filenames contain the correct code")
    ap.add_argument("--workers", type=int, default=0)
    args = ap.parse_args()

    pairs = (load_from_csv(Path(args.csv).expanduser()) if args.csv
             else load_from_folder(Path(args.input).expanduser()))
    missing = [p for p, _ in pairs if not p.exists()]
    for p in missing[:5]:
        print(f"warning: missing file {p}", file=sys.stderr)
    pairs = [(p, c) for p, c in pairs if p.exists()]

    if not pairs:
        print("No labelled images found.", file=sys.stderr)
        return 2

    workers = args.workers or BATCH_CONCURRENCY
    print(f"Scanning {len(pairs)} labelled image(s) with {workers} worker(s)...\n")
    ocr_pool.initialize()

    def scan(pair):
        path, expected = pair
        return path, expected, process_pipeline(path.read_bytes())

    with ThreadPoolExecutor(max_workers=workers) as pool:
        scanned = list(pool.map(scan, pairs))

    # Every image is scanned once; the threshold is applied afterwards. The
    # scan itself does not depend on OCR_MIN_CONFIDENCE, only the verdict does.
    print(f"{'threshold':>10} {'WRONG':>7} {'AUTO':>7} {'REVIEW':>7} {'FAILED':>7}   {'auto %':>7}")
    print("-" * 60)
    best = None
    rows = []
    for t in THRESHOLDS:
        wrong = auto = review = failed = 0
        for _, expected, r in scanned:
            if not r.code:
                failed += 1
                continue
            got = standardize_filename(r.code)
            # Mirror pipeline._decide: substitution and conflict force review
            # regardless of how high the score is.
            trustworthy = (r.confidence >= t
                           and not any(c.substituted for c in r.candidates[:1])
                           and len({c.code for c in r.candidates}) == 1)
            if not trustworthy:
                review += 1
            elif got == expected:
                auto += 1
            else:
                wrong += 1
        rows.append((t, wrong, auto, review, failed))
        pct = 100 * auto / len(scanned)
        flag = ""
        if wrong == 0 and best is None:
            best = t
            flag = "  <- lowest with zero wrong"
        print(f"{t:>10.3f} {wrong:>7} {auto:>7} {review:>7} {failed:>7}   {pct:>6.1f}%{flag}")

    print()
    mislabelled = [(p, e, r) for p, e, r in scanned
                   if r.code and standardize_filename(r.code) != e]
    if mislabelled:
        print(f"{len(mislabelled)} image(s) read as a code other than the label:")
        for p, e, r in mislabelled[:15]:
            print(f"  {p.name[:44]:<46} label={e:<10} read={r.code:<10} "
                  f"conf={r.confidence:.3f}  {r.reason}")
        print("  Check these by eye — a wrong LABEL looks identical to a wrong READ here.\n")

    if best is None:
        print("No threshold eliminated wrong renames. Those images need the review "
              "queue regardless; inspect the list above before trusting any setting.")
        return 1

    print(f"Current setting: OCR_MIN_CONFIDENCE={OCR_MIN_CONFIDENCE}")
    print(f"Zero wrong renames at: {best:.3f} on this sample of {len(scanned)}.")
    print("Add margin above it — real backlogs contain worse photographs than a sample.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
