import cv2
import re
import logging
from scanner.engine_pool import ocr_pool

logger = logging.getLogger("vr-saree-sorter.strategies.ocr")

def _clean_ocr_text(text: str) -> str:
    """Aggressively clean OCR text for VR code extraction."""
    clean = text.replace(" ", "").upper()
    ocr_digit_map = str.maketrans("OoIl|", "00111")
    clean = clean.translate(ocr_digit_map)
    clean = re.sub(r"[^A-Z0-9]", "", clean)
    return clean

def _ocr_with_rotations(engine, image) -> str | None:
    """Run DBNet across rotational passes"""
    rotations = [0, 180]
    best_match = None
    
    for angle in rotations:
        if angle == 180:
            rotated = cv2.rotate(image, cv2.ROTATE_180)
        else:
            rotated = image

        # Neural networks process raw images better than thresholded logic.
        ocr_result, _ = engine(rotated)
        if ocr_result:
            # Strategy 1: Check individual lines
            for _, text, _ in ocr_result:
                clean = _clean_ocr_text(text)
                if "VR" in clean:
                    match = re.search(r"VR\d{4,8}(?!\d)", clean)
                    if match: return match.group(0)
                    
                    vr_idx = clean.index("VR")
                    digits = "".join(filter(str.isdigit, clean[vr_idx+2:][:8]))
                    if 4 <= len(digits):
                        return f"VR{digits}"

            # Strategy 2: Concatenate everything fallback
            all_text = " ".join([line[1] for line in ocr_result])
            vr = _clean_ocr_text(all_text)
            if "VR" in vr:
                match = re.search(r"VR\d{4,8}(?!\d)", vr)
                if match:
                    candidate = match.group(0)
                    if best_match is None or len(candidate) > len(best_match):
                        best_match = candidate
                        
                if best_match is None:
                    vr_idx = vr.index("VR")
                    digits = "".join(filter(str.isdigit, vr[vr_idx+2:][:8]))
                    if 4 <= len(digits):
                        best_match = f"VR{digits}"
    
    return best_match

def scan_ocr(image, roi_image=None) -> str | None:
    """Strategy wrapper to orchestrate the OCR Object Pool."""
    engine = ocr_pool.acquire()
    try:
        images_to_try = []
        if roi_image is not None:
            # Upscale ROI locally to prevent dependency loops
            h, w = roi_image.shape[:2]
            scaled = cv2.resize(roi_image, (int(w*(1200/w)), int(h*(1200/w))), cv2.INTER_CUBIC) if w < 1200 else roi_image
            images_to_try.append(("roi", scaled))
        images_to_try.append(("full", image))
        
        for name, img in images_to_try:
            result = _ocr_with_rotations(engine, img)
            if result:
                logger.debug(f"OCR match found from {name} source")
                return result
    except Exception as e:
        logger.error(f"OCR processing error: {type(e).__name__}")
    finally:
        ocr_pool.release(engine)
        
    return None
