from __future__ import annotations
import cv2
import re
import logging
import zxingcpp
# from pyzbar.pyzbar import decode, ZBarSymbol
from core.config import ENABLE_BARCODE_SCANNER

logger = logging.getLogger("vr-saree-sorter.strategies.barcode")



# VR pattern: "VR" followed by digits. Applied to cleaned text.
VR_PATTERN = re.compile(r"VR\d+", re.IGNORECASE)

def _extract_vr_from_barcode(text: str) -> str | None:
    """
    Only accept barcode data that contains a VR code.
    Pure digit strings (UPC, EAN, etc.) are rejected — they fall through to OCR
    which has context-aware VR extraction from the printed label text.
    """
    clean = text.strip().upper()
    match = VR_PATTERN.search(clean)
    if match:
        return match.group(0)
    return None

def decode_barcode_robust(image) -> str | None:
    """Strategy wrapper for zxing-cpp. Only returns VR-pattern barcodes."""
    if not ENABLE_BARCODE_SCANNER:
        return None

    try:
        # Convert to grayscale: 3x less memory, better contrast for barcode reading
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        # Restrict to Code128 + QRCode only — the only formats on saree labels
        # This prevents reading UPC/EAN product barcodes and is faster
        vr_formats = zxingcpp.BarcodeFormat.Code128 | zxingcpp.BarcodeFormat.QRCode
        results = zxingcpp.read_barcodes(gray, formats=vr_formats)
        for result in results:
            if result.text:
                vr_code = _extract_vr_from_barcode(result.text)
                if vr_code:
                    logger.debug(f"zxing-cpp VR barcode found: {vr_code} (raw: {result.text})")
                    return vr_code
                else:
                    logger.debug(f"zxing-cpp rejected non-VR barcode: {result.text}")
    except Exception as e:
        logger.debug("zxing-cpp error: %s", str(e))

    # Legacy pyzbar implementation removed — see git history
    return None

