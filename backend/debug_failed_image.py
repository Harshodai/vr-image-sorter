"""
Run one image through the production pipeline with DEBUG logging on, so you can
see which stage found the code (or why nothing did).

    python debug_failed_image.py                       # defaults to test_user_image.jpg
    python debug_failed_image.py some_photo.jpeg       # a name inside tests/sandbox
    python debug_failed_image.py /full/path/to/img.jpg
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from scanner.pipeline import process_pipeline  # noqa: E402

SANDBOX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "sandbox")


def debug_image(filename: str) -> int:
    # Accept either a bare name inside tests/sandbox or a full path, so this
    # works on whatever machine it is run from.
    filepath = filename if os.path.isabs(filename) else os.path.join(SANDBOX_DIR, filename)
    if not os.path.exists(filepath):
        print(f"Error: could not find {filepath!r}")
        print(f"Available in {SANDBOX_DIR}:")
        for f in sorted(os.listdir(SANDBOX_DIR))[:20]:
            print(f"  {f}")
        return 1

    with open(filepath, "rb") as f:
        image_bytes = f.read()

    t_start = time.monotonic()
    result = process_pipeline(image_bytes)
    elapsed = time.monotonic() - t_start

    print(f"\n--> Code       : {result.code}")
    print(f"--> Confidence : {result.confidence:.4f}")
    print(f"--> Method     : {result.method}")
    print(f"--> Auto-rename: {result.is_confident}")
    print(f"--> Reason     : {result.reason}")
    if result.candidates:
        print("--> Candidates :")
        for c in result.candidates:
            print(f"      {c.code:<12} {c.confidence:.4f}  {c.source} rot{c.rotation}"
                  f"{'  (substituted)' if c.substituted else ''}")
    print(f"--> Elapsed    : {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "test_user_image.jpg"
    raise SystemExit(debug_image(target))
