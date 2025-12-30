import os
from easyocr import Reader

print("Starting EasyOCR model preload...")

# triggers download of detection (craft) and recognition (english) models
# gpu=False prevents it from looking for CUDA during build
reader = Reader(['en'], gpu=False, verbose=True)

# Verify downloads
model_dir = os.path.join(os.path.expanduser('~'), '.EasyOCR', 'model')
if os.path.exists(model_dir):
    print(f"✅ Models successfully downloaded to {model_dir}:")
    for f in os.listdir(model_dir):
        print(f" - {f}")
else:
    print("❌ ERROR: Model directory not found after initialization!")
