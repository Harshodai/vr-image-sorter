from __future__ import annotations

import logging
import re

import cv2

from scanner.engine_pool import ocr_pool

logger = logging.getLogger("vr-saree-sorter.strategies.ocr")

# Minimum width (px) for an ROI before we upscale it for better OCR accuracy.
_MIN_ROI_WIDTH = 1200

# Strict VR code pattern: "VR" followed by 4–8 digits, not immediately
# followed by another digit (prevents partial matches like VR12345678X).
_VR_PATTERN = re.compile(r"VR\d{4,8}(?!\d)")


def _clean_ocr_text(text: str) -> str:
    """Aggressively normalise OCR text for VR code extraction."""
    clean = text.replace(" ", "").upper()
    # Common OCR misreads: '/' or '\\' read instead of 'V' before 'R'
    clean = re.sub(r"[/\\]R(\d)", r"VR\1", clean)
    ocr_digit_map = str.maketrans("OoIl|", "00111")
    clean = clean.translate(ocr_digit_map)
    clean = re.sub(r"[^A-Z0-9]", "", clean)
    return clean


def _ocr_with_rotations(engine, image) -> str | None:
    """
    Run the OCR engine across 0° and 180° rotations.

    Strategy 1 — per-line scan: return immediately on the first confident hit.
    Strategy 2 — concatenated fallback: join all lines and search the result.
    The longer match wins in the concatenated pass (more digits = more specific).
    """
    best_match: str | None = None

    for angle in (0, 180):
        rotated = cv2.rotate(image, cv2.ROTATE_180) if angle == 180 else image

        try:
            # Neural networks process raw images better than thresholded logic.
            ocr_result, _ = engine(rotated)
        except Exception as exc:
            logger.debug("OCR engine call failed at %d°: %s", angle, type(exc).__name__)
            continue

        if not ocr_result:
            continue

        # Strategy 1: per-line early exit
        for _, text, confidence in ocr_result:
            clean = _clean_ocr_text(text)
            match = _VR_PATTERN.search(clean)
            if match:
                logger.debug(
                    "OCR line hit at %d° (conf=%.2f): %s",
                    angle, confidence or 0, match.group(0),
                )
                return match.group(0)

        # Strategy 2: concatenated fallback
        all_text = " ".join(line[1] for line in ocr_result)
        vr = _clean_ocr_text(all_text)
        match = _VR_PATTERN.search(vr)
        if match:
            candidate = match.group(0)
            if best_match is None or len(candidate) > len(best_match):
                best_match = candidate

    return best_match


def scan_ocr(image, roi_image=None) -> str | None:
    """
    Strategy wrapper that orchestrates the OCR engine pool.

    Tries the ROI crop first (upscaled if too small), then falls back to the
    full image.  The engine is always returned to the pool in the finally block.
    """
    try:
        engine = ocr_pool.acquire()
    except Exception as exc:
        logger.error("Could not acquire OCR engine: %s", type(exc).__name__)
        return None

    try:
        images_to_try: list[tuple[str, object]] = []

        if roi_image is not None:
            h, w = roi_image.shape[:2]
            if w < _MIN_ROI_WIDTH and w > 0:
                scale = _MIN_ROI_WIDTH / w
                scaled = cv2.resize(
                    roi_image,
                    (int(w * scale), int(h * scale)),
                    interpolation=cv2.INTER_CUBIC,
                )
            else:
                scaled = roi_image
            images_to_try.append(("roi", scaled))

        images_to_try.append(("full", image))

        for name, img in images_to_try:
            result = _ocr_with_rotations(engine, img)
            if result:
                logger.debug("OCR match found from %s source: %s", name, result)
                return result

    except Exception as exc:
        logger.error("OCR processing error: %s", type(exc).__name__, exc_info=True)
    finally:
        ocr_pool.release(engine)

    return None
