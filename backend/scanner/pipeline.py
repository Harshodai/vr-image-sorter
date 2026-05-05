from __future__ import annotations

import logging
import time

import cv2
import numpy as np

from scanner.utils import detect_label_regions
from scanner.strategies.barcode import decode_barcode_robust
from scanner.strategies.ocr import scan_ocr

logger = logging.getLogger("vr-saree-sorter.pipeline")

# Maximum dimension (px) before downscaling to prevent OOM on large images.
_MAX_DIM = 1200


def _decode_image(image_bytes: bytes):
    """
    Decode raw bytes into an OpenCV BGR image, downscaling if necessary.
    Returns the image array or None on failure.
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            logger.warning("cv2.imdecode returned None — unsupported or corrupt image")
            return None

        h, w = image.shape[:2]
        if max(h, w) > _MAX_DIM:
            scale = _MAX_DIM / max(h, w)
            image = cv2.resize(
                image,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
            logger.debug("Downscaled image from %dx%d to %dx%d", w, h, int(w * scale), int(h * scale))

        return image
    except Exception as exc:
        logger.error("Image decoding error: %s", type(exc).__name__)
        return None


def process_pipeline(image_bytes: bytes) -> str | None:
    """
    Attempt to extract a VR code from *image_bytes* using the SOLID Pipeline
    Pattern:

      1. Detect white label regions (ROI extraction).
      2. Barcode scan on each label crop (fast path).
      3. Barcode scan on the full image (fallback).
      4. OCR on the best label crop + full image (deep fallback).
      5. OCR on remaining label crops (exhaustive fallback).

    Each step is wrapped in its own try/except so a failure in one strategy
    never prevents the next from running.
    """
    t0 = time.monotonic()

    original_image = _decode_image(image_bytes)
    if original_image is None:
        return None

    # ── Step 1: Detect label regions ────────────────────────────────────
    try:
        label_crops = detect_label_regions(original_image)
        logger.debug("Detected %d label region(s)", len(label_crops))
    except Exception as exc:
        logger.error("Label detection error: %s", type(exc).__name__, exc_info=True)
        label_crops = []

    # ── Step 2: Barcode on label crops ──────────────────────────────────
    for i, crop in enumerate(label_crops):
        try:
            result = decode_barcode_robust(crop)
            if result:
                logger.info("Barcode found on label crop %d (%.2fs)", i, time.monotonic() - t0)
                return result
        except Exception as exc:
            logger.debug("Barcode error on crop %d: %s", i, type(exc).__name__)

    # ── Step 3: Barcode on full image ───────────────────────────────────
    try:
        full_barcode = decode_barcode_robust(original_image)
        if full_barcode:
            logger.info("Barcode found on full image (%.2fs)", time.monotonic() - t0)
            return full_barcode
    except Exception as exc:
        logger.debug("Barcode error on full image: %s", type(exc).__name__)

    # ── Step 4: OCR on best label crop + full image ──────────────────────
    logger.debug("Attempting OCR fallback")
    best_roi = label_crops[0] if label_crops else None
    try:
        ocr_result = scan_ocr(original_image, roi_image=best_roi)
        if ocr_result:
            logger.info("OCR match on primary pass (%.2fs)", time.monotonic() - t0)
            return ocr_result
    except Exception as exc:
        logger.error("OCR primary pass error: %s", type(exc).__name__, exc_info=True)

    # ── Step 5: OCR on remaining label crops ────────────────────────────
    if len(label_crops) > 1:
        for j, crop in enumerate(label_crops[1:], start=1):
            try:
                ocr_result = scan_ocr(crop)
                if ocr_result:
                    logger.info("OCR match on label crop %d (%.2fs)", j, time.monotonic() - t0)
                    return ocr_result
            except Exception as exc:
                logger.debug("OCR error on crop %d: %s", j, type(exc).__name__)

    logger.debug("Pipeline exhausted — no VR code found (%.2fs)", time.monotonic() - t0)
    return None
