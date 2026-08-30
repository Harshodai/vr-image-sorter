from __future__ import annotations
import cv2
import re
import logging
import zxingcpp
# from pyzbar.pyzbar import decode, ZBarSymbol
from core.config import ENABLE_BARCODE_SCANNER

logger = logging.getLogger("vr-saree-sorter.strategies.barcode")



# VR pattern: "VR" followed by 4-8 digits.
VR_EXPLICIT_PATTERN = re.compile(r"VR\d{4,8}(?!\d)", re.IGNORECASE)
# Pure SKU digit pattern (5-7 digits) used in saree retail barcodes (e.g., 173873 or 221130)
VR_DIGIT_PATTERN = re.compile(r"(?:^|[^\d])(\d{5,7})(?:[^\d]|$)", re.IGNORECASE)

def _extract_vr_from_barcode(text: str) -> str | None:
    """
    Extract VR code from barcode data.
    Supports:
      1. Direct VR codes: 'VR173873', 'VR221130'
      2. Delimited codes: 'VR173873/251130', '173873-251130'
      3. Pure 5-7 digit SKU barcodes from saree ERPs: '173873' -> 'VR173873'
    """
    clean = text.strip().upper()
    
    # 1. Direct VR pattern match
    match = VR_EXPLICIT_PATTERN.search(clean)
    if match:
        return match.group(0).upper()

    # 2. Check for delimited format e.g. "173873/251130" or "173873 251130"
    tokens = re.split(r"[\s/\-_|]+", clean)
    for tok in tokens:
        m = VR_EXPLICIT_PATTERN.search(tok)
        if m:
            return m.group(0).upper()
        if re.fullmatch(r"\d{5,7}", tok):
            return f"VR{tok}"

    # 3. Check for standalone 5-7 digits (ignoring standard 12/13-digit EAN/UPC)
    if len(clean) >= 5 and len(clean) <= 7 and clean.isdigit():
        return f"VR{clean}"
        
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

