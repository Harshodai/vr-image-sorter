from __future__ import annotations
import cv2
import numpy as np
import logging
from scanner.utils import detect_label_regions
from scanner.strategies.barcode import decode_barcode_robust
from scanner.strategies.ocr import scan_ocr

logger = logging.getLogger("vr-saree-sorter.pipeline")

def process_pipeline(image_bytes: bytes) -> str | None:
    """
    Attempts to scan a barcode/VR code from image bytes utilizing
    the SOLID Pipeline Pattern.
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        original_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if original_image is None:
            logger.warning("Could not decode image bytes")
            return None
            
        # Prevent OOMs from massive images: Downscale if larger than 1200px
        MAX_DIM = 1200
        h, w = original_image.shape[:2]
        if max(h, w) > MAX_DIM:
            scale = MAX_DIM / max(h, w)
            new_w = int(w * scale)
            new_h = int(h * scale)
            original_image = cv2.resize(original_image, (new_w, new_h), interpolation=cv2.INTER_AREA)
            
    except Exception as e:
        logger.error("Image decoding error: %s", type(e).__name__)
        return None

    # Step 1: Detect label regions
    label_crops = detect_label_regions(original_image)
    logger.debug("Detected %d label regions", len(label_crops))
    
    # Step 2: Try barcode on label crops first
    for i, crop in enumerate(label_crops):
        result = decode_barcode_robust(crop)
        if result:
            logger.info("Barcode found on label crop %d", i)
            return result
    
    # Step 3: Try barcode on full image (VR-pattern filter rejects UPC/EAN automatically)
    full_barcode = decode_barcode_robust(original_image)
    if full_barcode:
        logger.info("Barcode found on full image scan")
        return full_barcode
    
    # Step 4: Try RapidOCR Deep Learning Strategy on label crops then full image
    logger.debug("Attempting OCR fallback")
    best_roi = label_crops[0] if label_crops else None
    ocr_result = scan_ocr(original_image, roi_image=best_roi)
    if ocr_result:
        return ocr_result
    
    # Step 5: Full fallback — OCR on remaining label crops
    if len(label_crops) > 1:
        for crop in label_crops[1:]:
            ocr_result = scan_ocr(crop)
            if ocr_result:
                return ocr_result

    return None
