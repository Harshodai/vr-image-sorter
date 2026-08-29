"""
Folder-based sorter for large backlogs.

The web UI is fine for a few hundred images. It is not viable for 100k: the
browser has to hold every File object and preview blob in memory, and a crash
part-way through loses the whole run. This reads straight off disk instead,
records progress after every image, and resumes where it stopped.

    python cli.py sort  --input ./photos --output ./sorted
    python cli.py sort  --input ./photos --output ./sorted --resume
    python cli.py watch --input ./dropbox --output ./sorted

Output layout:
    sorted/renamed/   confidently identified, renamed to VR<digits>.<ext>
    sorted/review/    a code was read but is not trustworthy — original name kept
    sorted/failed/    nothing readable — original name kept
    sorted/manifest.jsonl   one record per image; also the resume index
    sorted/review.csv       the review queue as a spreadsheet
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import (  # noqa: E402
    ALLOWED_EXTENSIONS, BATCH_CONCURRENCY, OCR_POOL_SIZE, RETRY_SCAN_DIMENSION,
)
from scanner.engine_pool import ocr_pool  # noqa: E402
from scanner.pipeline import process_pipeline  # noqa: E402
from scanner.utils import standardize_filename  # noqa: E402

MANIFEST = "manifest.jsonl"
_stop = False


def _handle_signal(signum, frame):
    """Finish the images already in flight, then stop cleanly so --resume works."""
    global _stop
    if _stop:
        print("\nForced exit; the manifest may be missing the in-flight images.")
        sys.exit(130)
    _stop = True
    print("\nStopping after the images currently in flight. Ctrl-C again to force.")


def iter_images(root: Path, recursive: bool):
    pattern = "**/*" if recursive else "*"
    for path in sorted(root.glob(pattern)):
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
            yield path


def load_done(manifest: Path) -> set[str]:
    """Source paths already recorded, so a resumed run skips them."""
    if not manifest.exists():
        return set()
    done = set()
    with manifest.open() as fh:
        for line in fh:
            try:
                done.add(json.loads(line)["source"])
            except Exception:
                continue  # a torn final line from a hard kill is expected
    return done


def unique_path(directory: Path, name: str) -> Path:
    base, ext = os.path.splitext(name)
    path, counter = directory / name, 1
    while path.exists():
        path = directory / f"{base}_{counter}{ext}"
        counter += 1
    return path


def scan_one(path: Path, max_dim: int | None):
    try:
        data = path.read_bytes()
    except Exception as e:
        return path, None, f"unreadable file: {type(e).__name__}"
    return path, process_pipeline(data, max_dim), None


def place(path: Path, result, dirs, copy: bool) -> dict:
    """Move or copy one scanned image into its bucket and return its manifest record."""
    ext = path.suffix.lower()
    record = {
        "source": str(path),
        "code": result.code if result else None,
        "confidence": round(result.confidence, 4) if result else 0.0,
        "method": result.method if result else "none",
        "reason": result.reason if result else "",
    }

    if result and result.is_confident:
        dest = unique_path(dirs["renamed"], f"{standardize_filename(result.code)}{ext}")
        record["status"] = "renamed"
    elif result and result.code:
        dest = unique_path(dirs["review"], path.name)
        record["status"] = "review"
        record["suggested"] = result.code
        record["alternatives"] = [
            {"code": c.code, "confidence": round(c.confidence, 4)} for c in result.candidates[:5]
        ]
    else:
        dest = unique_path(dirs["failed"], path.name)
        record["status"] = "failed"

    (shutil.copy2 if copy else shutil.move)(str(path), str(dest))
    record["dest"] = str(dest)
    return record


def run_batch(paths, dirs, manifest: Path, workers: int, copy: bool, max_dim: int | None) -> dict:
    counts = {"renamed": 0, "review": 0, "failed": 0}
    if not paths:
        return counts

    total = len(paths)
    started = time.monotonic()
    done = 0

    # Append-and-flush per image: a run that dies at image 90,000 must not lose
    # the record of the 89,999 before it.
    with manifest.open("a") as mf, ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_one, p, max_dim): p for p in paths}
        for future in as_completed(futures):
            path, result, error = future.result()
            if error:
                record = {"source": str(path), "status": "failed", "reason": error,
                          "code": None, "confidence": 0.0, "method": "none"}
            else:
                try:
                    record = place(path, result, dirs, copy)
                except Exception as e:
                    record = {"source": str(path), "status": "failed", "code": None,
                              "confidence": 0.0, "method": "none",
                              "reason": f"could not file image: {type(e).__name__}"}

            counts[record["status"]] = counts.get(record["status"], 0) + 1
            mf.write(json.dumps(record) + "\n")
            mf.flush()

            done += 1
            elapsed = time.monotonic() - started
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(f"\r  {done}/{total}  {rate:.2f} img/s  "
                  f"renamed={counts['renamed']} review={counts['review']} failed={counts['failed']}  "
                  f"ETA {eta/3600:.1f}h   ", end="", flush=True)

            if _stop:
                for f in futures:
                    f.cancel()
                break
    print()
    return counts


def write_review_csv(manifest: Path, out: Path):
    """The review queue as a spreadsheet: open it, fill in `corrected_code`."""
    rows = []
    if manifest.exists():
        with manifest.open() as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("status") in ("review", "failed"):
                    rows.append(r)
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "status", "suggested_code", "confidence", "reason", "corrected_code"])
        for r in rows:
            w.writerow([r.get("dest") or r["source"], r["status"], r.get("suggested", ""),
                        r.get("confidence", ""), r.get("reason", ""), ""])
    return len(rows)


def apply_csv(csv_path: Path, out_root: Path) -> int:
    """Apply human corrections: move reviewed images into renamed/ under their real code."""
    renamed_dir = out_root / "renamed"
    renamed_dir.mkdir(parents=True, exist_ok=True)
    applied = 0
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            code = standardize_filename((row.get("corrected_code") or "").strip())
            src = Path(row["file"])
            if not code or not src.exists():
                continue
            dest = unique_path(renamed_dir, f"{code}{src.suffix.lower()}")
            shutil.move(str(src), str(dest))
            applied += 1
    return applied


def prepare(output: Path) -> dict:
    dirs = {name: output / name for name in ("renamed", "review", "failed")}
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def cmd_sort(args) -> int:
    src, out = Path(args.input).expanduser(), Path(args.output).expanduser()
    if not src.is_dir():
        print(f"error: --input is not a directory: {src}", file=sys.stderr)
        return 2

    dirs = prepare(out)
    manifest = out / MANIFEST
    images = list(iter_images(src, args.recursive))

    if args.resume:
        done = load_done(manifest)
        before = len(images)
        images = [p for p in images if str(p) not in done]
        print(f"Resuming: {before - len(images)} already recorded, {len(images)} remaining.")
    elif manifest.exists():
        print(f"warning: {manifest} exists. Use --resume to continue, or delete it "
              f"to start over. Continuing would duplicate its records.", file=sys.stderr)
        return 2

    if not images:
        print("Nothing to do.")
        return 0

    workers = args.workers or BATCH_CONCURRENCY
    print(f"{len(images)} image(s), {workers} worker(s), engine pool {OCR_POOL_SIZE}, "
          f"{'copying' if args.copy else 'moving'} into {out}")

    started = time.monotonic()
    counts = run_batch(images, dirs, manifest, workers, args.copy, args.max_dim)
    elapsed = time.monotonic() - started

    n = sum(counts.values())
    print(f"\nDone: {n} image(s) in {elapsed/60:.1f} min "
          f"({n/elapsed if elapsed else 0:.2f} img/s)")
    print(f"  renamed automatically : {counts['renamed']}")
    print(f"  needs review          : {counts['review']}")
    print(f"  unreadable            : {counts['failed']}")

    queued = write_review_csv(manifest, out / "review.csv")
    if queued:
        print(f"\n{queued} image(s) need a human. Open {out/'review.csv'}, fill in "
              f"'corrected_code', then run:\n  python cli.py apply --csv {out/'review.csv'} "
              f"--output {out}")
    if _stop:
        print("\nStopped early. Re-run with --resume to continue.")
    return 0


def cmd_watch(args) -> int:
    src, out = Path(args.input).expanduser(), Path(args.output).expanduser()
    if not src.is_dir():
        print(f"error: --input is not a directory: {src}", file=sys.stderr)
        return 2

    dirs = prepare(out)
    manifest = out / MANIFEST
    workers = args.workers or BATCH_CONCURRENCY
    seen = load_done(manifest)
    print(f"Watching {src} every {args.interval}s. Ctrl-C to stop.")

    while not _stop:
        batch = [p for p in iter_images(src, args.recursive) if str(p) not in seen]
        # Skip files still being written: require the size to hold steady.
        ready = []
        for p in batch:
            try:
                size = p.stat().st_size
                time.sleep(0.05)
                if size == p.stat().st_size and size > 0:
                    ready.append(p)
            except OSError:
                continue

        if ready:
            print(f"\n{len(ready)} new image(s)")
            run_batch(ready, dirs, manifest, workers, args.copy, args.max_dim)
            seen.update(str(p) for p in ready)
            write_review_csv(manifest, out / "review.csv")
        else:
            time.sleep(args.interval)
    print("\nStopped.")
    return 0


def cmd_apply(args) -> int:
    csv_path, out = Path(args.csv).expanduser(), Path(args.output).expanduser()
    if not csv_path.exists():
        print(f"error: no such file: {csv_path}", file=sys.stderr)
        return 2
    applied = apply_csv(csv_path, out)
    print(f"Applied {applied} correction(s) into {out/'renamed'}")
    return 0


def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    parser = argparse.ArgumentParser(
        prog="cli.py", description="Sort saree images into folders by VR code.")
    sub = parser.add_subparsers(dest="command", required=True)

    def shared(p):
        p.add_argument("--input", required=True, help="folder of images to read")
        p.add_argument("--output", required=True, help="folder to write results into")
        p.add_argument("--workers", type=int, default=0,
                       help=f"images in flight (default {BATCH_CONCURRENCY}, from core count)")
        p.add_argument("--copy", action="store_true",
                       help="copy instead of move, leaving the input folder untouched")
        p.add_argument("--recursive", action="store_true", help="descend into subfolders")
        p.add_argument("--max-dim", type=int, default=0,
                       help="working resolution; higher reads small text better but is slower")

    s = sub.add_parser("sort", help="process a folder once")
    shared(s)
    s.add_argument("--resume", action="store_true", help="skip images already in the manifest")
    s.set_defaults(func=cmd_sort)

    w = sub.add_parser("watch", help="process images as they appear in a folder")
    shared(w)
    w.add_argument("--interval", type=float, default=5.0, help="seconds between scans")
    w.set_defaults(func=cmd_watch)

    a = sub.add_parser("apply", help="apply corrected codes from review.csv")
    a.add_argument("--csv", required=True)
    a.add_argument("--output", required=True)
    a.set_defaults(func=cmd_apply)

    args = parser.parse_args()
    if hasattr(args, "max_dim"):
        args.max_dim = args.max_dim or None
    ocr_pool.initialize()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
