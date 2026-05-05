from __future__ import annotations

import logging
import re

import cv2
import zxingcpp

from core.config import ENABLE_BARCODE_SCANNER

logger = logging.getLogger("vr-saree-sorter.strategies.barcode")

# VR pattern: "VR" followed by digits. Applied to cleaned barcode text.
# Intentionally permissive on digit count here — the OCR layer enforces
# the 4–8 digit constraint; barcodes encode the exact string.
_VR_PATTERN = re.compile(r"VR\d+", re.IGNORECASE)

# Restrict to the only formats found on saree labels.
# This prevents reading UPC/EAN product barcodes and is significantly faster
# than scanning all supported formats.
_VR_FORMATS = zxingcpp.BarcodeFormat.Code128 | zxingcpp.BarcodeFormat.QRCode


def _extract_vr_from_barcode(text: str) -> str | None:
    """
    Only accept barcode data that contains a VR code.
    Pure digit strings (UPC, EAN, etc.) are rejected — they fall through to
    OCR which has context-aware VR extraction from the printed label text.
    """
    clean = text.strip().upper()
    match = _VR_PATTERN.search(clean)
    if match:
        return match.group(0)
    return None


def decode_barcode_robust(image) -> str | None:
    """
    Strategy wrapper for zxing-cpp.  Only returns VR-pattern barcodes.

    Converts to grayscale first (3× less memory, better contrast) then
    restricts the format search to Code128 + QRCode for speed.  Returns on
    the first valid VR code found (early exit).
    """
    if not ENABLE_BARCODE_SCANNER:
        return None

    try:
        # Convert to grayscale: 3× less memory, better contrast for barcode reading.
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image

        results = zxingcpp.read_barcodes(gray, formats=_VR_FORMATS)
        for result in results:
            if not result.text:
                continue
            vr_code = _extract_vr_from_barcode(result.text)
            if vr_code:
                logger.debug("zxing-cpp VR barcode found: %s (raw: %s)", vr_code, result.text)
                return vr_code  # Early exit on first valid hit
            else:
                logger.debug("zxing-cpp rejected non-VR barcode: %s", result.text)

    except Exception as exc:
        logger.debug("zxing-cpp error: %s", exc)

    # Legacy pyzbar implementation removed — see git history.
    return None

