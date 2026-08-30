"""
Quick benchmark: timing on ../input images.
"""

import glob
import os
import sys
import time

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scanner.pipeline import process_pipeline


def main():
    input_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "input")
    fs = sorted(glob.glob(os.path.join(input_dir, "*")))
    if not fs:
        print("No images found in ./input/")
        return

    t0 = time.monotonic()
    results = [process_pipeline(open(f, "rb").read()) for f in fs]
    elapsed = time.monotonic() - t0
    total = max(len(fs), 1)
    hits = sum(1 for x in results if x and x.code)
    print(f"{len(fs)} imgs in {elapsed:.2f}s ({elapsed/total:.2f}s/img) - hits={hits}/{len(fs)}")


if __name__ == "__main__":
    main()
