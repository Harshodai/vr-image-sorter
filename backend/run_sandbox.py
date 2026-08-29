"""
Scan every image in tests/sandbox exactly as the API would, and print the
verdict for each. Handy for eyeballing a change to the pipeline.

    python run_sandbox.py
"""
import io
import os
import sys

# Windows terminals choke on the default encoding for some filenames.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import ALLOWED_EXTENSIONS  # noqa: E402
from scanner.pipeline import process_pipeline  # noqa: E402

SANDBOX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "sandbox")

print("Scanning images in sandbox exactly as the API would:")
print("-" * 78)

renamed = review = failed = 0
for filename in sorted(os.listdir(SANDBOX_DIR)):
    filepath = os.path.join(SANDBOX_DIR, filename)
    if not os.path.isfile(filepath):
        continue
    if os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS:
        continue

    with open(filepath, "rb") as f:
        result = process_pipeline(f.read())

    if result.is_confident:
        renamed += 1
        verdict = f"RENAME -> {result.code}"
    elif result.code:
        review += 1
        verdict = f"REVIEW -> {result.code} ({result.reason})"
    else:
        failed += 1
        verdict = f"NONE   ({result.reason})"

    print(f"{filename[:46]:<48} {verdict}")

print("-" * 78)
print(f"auto-renamed={renamed}  needs-review={review}  unreadable={failed}")
