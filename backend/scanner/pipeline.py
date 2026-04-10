import cv2
import numpy as np
import logging
import gc
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
            
        # Prevent OOMs from massive images: Downscale if larger than 2000px
        MAX_DIM = 2000
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
    
    # Step 2: Try PyZbar Barcode Strategy on explicit crops
    for i, crop in enumerate(label_crops):
        result = decode_barcode_robust(crop)
        if result:
            logger.info("Barcode found on label crop %d", i)
            gc.collect()
            return result
    
    # Step 3: Try RapidOCR Deep Learning Strategy on label crops then full image
    logger.debug("Attempting OCR fallback")
    best_roi = label_crops[0] if label_crops else None
    ocr_result = scan_ocr(original_image, roi_image=best_roi)
    if ocr_result:
        gc.collect()
        return ocr_result
    
    # Step 4: Full fallback
    if len(label_crops) > 1:
        for crop in label_crops[1:]:
            ocr_result = scan_ocr(crop)
            if ocr_result:
                gc.collect()
                return ocr_result

    gc.collect()
    return None
