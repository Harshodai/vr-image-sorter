import cv2
import numpy as np
import logging
from pyzbar.pyzbar import decode, ZBarSymbol
from core.config import ENABLE_BARCODE_SCANNER

logger = logging.getLogger("vr-saree-sorter.strategies.barcode")

# Fast static filter constants
STRONG_SHARPEN_KERNEL = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])

def decode_barcode_robust(image) -> str | None:
    """Strategy wrapper for PyZbar. Falls back on internal processing rules."""
    if not ENABLE_BARCODE_SCANNER:
        return None

    symbols = [
        ZBarSymbol.CODE128, ZBarSymbol.QRCODE,
        ZBarSymbol.CODE39, ZBarSymbol.EAN13, ZBarSymbol.I25,
    ]
    
    h, w = image.shape[:2]
    scales = [1.0]
    if w < 200: scales = [5.0, 4.0, 3.0]
    elif w < 400: scales = [3.0, 2.0]
    elif w < 800: scales = [2.0, 3.0, 1.0]
    elif w < 1200: scales = [1.5, 1.0]

    methods = ["original", "grayscale", "threshold_otsu", "sharpen_heavy"]
    rotations = [0, 90]

    for scale in scales:
        if scale != 1.0:
            scaled = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)
        else:
            scaled = image
        
        for method in methods:
            if method == "sharpen_heavy":
                processed = cv2.filter2D(scaled, -1, STRONG_SHARPEN_KERNEL)
                gray = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
                _, processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            elif method == "grayscale":
                processed = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY) if len(scaled.shape) == 3 else scaled
            elif method == "threshold_otsu":
                gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY) if len(scaled.shape) == 3 else scaled
                _, processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            else:
                processed = scaled
            
            for angle in rotations:
                if angle == 0: img_to_scan = processed
                elif angle == 90: img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_CLOCKWISE)
                elif angle == 180: img_to_scan = cv2.rotate(processed, cv2.ROTATE_180)
                else: img_to_scan = cv2.rotate(processed, cv2.ROTATE_90_COUNTERCLOCKWISE)
                
                try:
                    barcodes = decode(img_to_scan, symbols=symbols)
                    for barcode in barcodes:
                        data = barcode.data.decode("utf-8")
                        if data:
                            logger.debug("Barcode found: scale=%.1f method=%s angle=%d", scale, method, angle)
                            return data
                except Exception as e:
                    logger.debug("Barcode scan error: %s", str(e))
    
    return None
