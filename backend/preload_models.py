import os
from rapidocr_onnxruntime import RapidOCR

print("Starting RapidOCR model preload...")

# Instantiate to initialize ONNX sessions and load models into memory/cache
ocr = RapidOCR()

print("✅ RapidOCR successfully initialized!")
