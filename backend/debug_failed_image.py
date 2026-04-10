import os
import sys
import io
import logging
import cv2

# Fix unicode characters crashing windows terminals 
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Enable debug logging for main.py
logging.getLogger("main").setLevel(logging.DEBUG)

from main import SareeSorter

filepath = r"C:\Users\khars\PycharmProjects\vr-image-sorter\tests\sandbox"

sorter = SareeSorter()
engine = sorter.get_reader()

print(f"Scanning image: {filepath}")
print("-" * 60)

image = cv2.imread(filepath)
# Downscale for sanity
MAX_DIM = 2000
h, w = image.shape[:2]
if max(h, w) > MAX_DIM:
    scale = MAX_DIM / max(h, w)
    image = cv2.resize(image, (int(w * scale), int(h * scale)))

for angle in [0, 180]:
    rot = cv2.rotate(image, cv2.ROTATE_180) if angle == 180 else image
    for method in ["original", "grayscale", "threshold_otsu"]:
        proc = sorter.preprocess_image(rot, method)
        results, _ = engine(proc)
        if results:
            print(f"Angle {angle}, Method {method} found {len(results)} text boxes:")
            for b, t, c in results:
                print(f"   [{c}] '{t}'")

result = sorter.scan_barcode_from_bytes(open(filepath, "rb").read())
print(f"\n--> Final Output: {result}")
