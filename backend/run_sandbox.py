import os
from main import SareeSorter
import sys
import io

# Fix unicode characters crashing windows terminals 
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SANDBOX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "sandbox")
sorter = SareeSorter()
sorter.get_reader()

print("Scanning images in sandbox exactly as the API would:")
print("-" * 60)

for filename in os.listdir(SANDBOX_DIR):
    filepath = os.path.join(SANDBOX_DIR, filename)
    if not os.path.isfile(filepath):
        continue
        
    with open(filepath, "rb") as f:
        image_bytes = f.read()
        
    result = sorter.scan_barcode_from_bytes(image_bytes)
    
    if result:
        print(f"File: {filename}\n--> Found VR Code: {result}\n")
    else:
        print(f"File: {filename}\n--> Output: NONE FOUND\n")
