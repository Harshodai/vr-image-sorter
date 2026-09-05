from __future__ import annotations
import cv2
import re
import logging
import numpy as np
from core.config import OCR_EARLY_EXIT_CONFIDENCE, ROI_TARGET_WIDTH
from scanner.engine_pool import ocr_pool
from scanner.result import Candidate

logger = logging.getLogger("vr-saree-sorter.strategies.ocr")

# VR followed by 4-8 digits (not followed by more digits, e.g. not VRP or VRS).
VR_RX = re.compile(r"VR\d{4,8}(?!\d)")
# Fragment pattern for split boxes across creases (e.g. VR1738 + 73)
VR_PREFIX_RX = re.compile(r"VR\d{1,6}$")
DIGITS_ONLY_RX = re.compile(r"^\d{1,6}$")

# Valid full VR code suffix lengths (digits after "VR"): 4–8.
# For crease-stitch candidates, we validate the merged digit count before
# deciding whether the candidate is trusted or routes to review.
_TRUSTED_VR_DIGIT_LENGTHS = frozenset(range(4, 9))  # 4,5,6,7,8

_DIGIT_MAP = str.maketrans("OoIl|", "00111")

# Maximum number of boxes to consider in the inner stitch loop to avoid
# O(n²) blowup on busy labels with many text regions.
_MAX_STITCH_INNER = 20


def _normalise(text: str, substitute: bool) -> str:
    clean = text.strip().upper()
    # Common OCR misread: '/' or '\' seen instead of 'V' before 'R'
    clean = re.sub(r"[/\\]R(\d)", r"VR\1", clean)
    # Fix VR space digits e.g. "VR 173873" -> "VR173873"
    # NOTE: previously r"...(\\d)" — a raw string's \\d is a literal
    # backslash followed by 'd', not the digit class, so this never matched
    # anything. It happened to cause no visible failures because the
    # whitespace-stripping fallback a few lines down in _extract() already
    # collapses "VR 173873" to "VR173873" before matching. Fixed to \d so
    # this line actually does what the comment says instead of relying on
    # a fallback that isn't guaranteed to run for every caller.
    clean = re.sub(r"\bVR[\s\-_.:]+(\d)", r"VR\1", clean)
    if substitute:
        clean = clean.translate(_DIGIT_MAP)
    return clean


def _extract(text: str) -> list[tuple[str, bool]]:
    """
    Token-aware extraction of VR codes from a line of text.
    Preserves multi-word lines like 'VR173873 251130' without jamming tokens together.
    Returns list of (code, substituted).
    """
    found: list[tuple[str, bool]] = []

    # 1. First test whitespace/delimiter-separated tokens
    tokens = re.split(r"[\s,;|/]+", text)
    for tok in tokens:
        if not tok:
            continue
        clean_strict = _normalise(tok, substitute=False)
        m_strict = VR_RX.search(clean_strict)
        if m_strict:
            found.append((m_strict.group(0), False))
            continue

        clean_loose = _normalise(tok, substitute=True)
        m_loose = VR_RX.search(clean_loose)
        if m_loose:
            found.append((m_loose.group(0), True))

    if found:
        return found

    # 2. Test entire string without spaces if tokens didn't match
    clean_strict = re.sub(r"[^A-Z0-9]", "", _normalise(text, substitute=False))
    m_strict = VR_RX.search(clean_strict)
    if m_strict:
        return [(m_strict.group(0), False)]

    clean_loose = re.sub(r"[^A-Z0-9]", "", _normalise(text, substitute=True))
    m_loose = VR_RX.search(clean_loose)
    if m_loose:
        return [(m_loose.group(0), True)]

    return []


def _box_center_and_height(box) -> tuple[float, float, float, float, float] | None:
    """Calculate center_x, center_y, height, left, and right of an OCR bounding box."""
    if box is None:
        return None
    try:
        pts = np.array(box, dtype=np.float32)
        if pts.ndim == 1 and pts.size >= 4:
            left = float(min(pts[0], pts[2]))
            right = float(max(pts[0], pts[2]))
            cx = float(pts[0] + pts[2]) / 2.0
            cy = float(pts[1] + pts[3]) / 2.0
            h = float(max(1.0, abs(pts[3] - pts[1])))
            return cx, cy, h, left, right
        elif pts.ndim == 2 and pts.shape[0] >= 2 and pts.shape[1] >= 2:
            min_x, max_x = float(np.min(pts[:, 0])), float(np.max(pts[:, 0]))
            min_y, max_y = float(np.min(pts[:, 1])), float(np.max(pts[:, 1]))
            cx = (min_x + max_x) / 2.0
            cy = (min_y + max_y) / 2.0
            h = float(max(1.0, max_y - min_y))
            return cx, cy, h, min_x, max_x
    except Exception:
        pass
    return None


def _stitch_crease_boxes(ocr_result) -> list[tuple[str, float, bool]]:
    """
    Stitch adjacent text boxes on the same horizontal baseline that were split
    by a fold/crease (e.g., Box1='VR1738', Box2='73' -> 'VR173873').

    Returns list of (code, score, substituted).
    Stitched candidates are marked substituted=True when the merged digit count
    is not a known ERP SKU length (4–8 digits after VR), routing them to review.
    """
    stitched: list[tuple[str, float, bool]] = []
    if not ocr_result:
        return stitched

    n = len(ocr_result)
    for i in range(n):
        try:
            line1 = ocr_result[i]
            if len(line1) < 3:
                continue
            box1, text1, score1 = line1[0], line1[1], line1[2]
            norm1 = _normalise(text1, substitute=False)
            m_prefix = VR_PREFIX_RX.search(norm1)
            if not m_prefix:
                continue

            b1_info = _box_center_and_height(box1)
            if not b1_info:
                continue
            cx1, cy1, h1, left1, right1 = b1_info
            prefix_code = m_prefix.group(0)

            # Look for adjacent numeric box to the right on the same horizontal line.
            # Limit inner loop to avoid O(n²) on busy labels.
            inner_candidates = [
                ocr_result[j] for j in range(n)
                if j != i
            ][:_MAX_STITCH_INNER]

            for line2 in inner_candidates:
                if len(line2) < 3:
                    continue
                box2, text2, score2 = line2[0], line2[1], line2[2]
                norm2 = _normalise(text2, substitute=False)
                m_digits = DIGITS_ONLY_RX.match(norm2) or re.match(r"^(\d{1,6})\b", norm2)
                if not m_digits:
                    continue

                b2_info = _box_center_and_height(box2)
                if not b2_info:
                    continue
                cx2, cy2, h2, left2, right2 = b2_info

                max_h = max(h1, h2)
                h_gap = left2 - right1
                # Same horizontal baseline: vertical difference is small relative to text height,
                # box2 is to the right of box1, and horizontal edge-to-edge gap is bounded
                if abs(cy1 - cy2) <= max_h * 0.75 and cx2 > cx1 and -max_h * 0.5 <= h_gap <= max_h * 2.0:
                    digits = m_digits.group(1) if m_digits.lastindex else m_digits.group(0)
                    merged = prefix_code + digits
                    m_full = VR_RX.search(merged)
                    if m_full:
                        combined_code = m_full.group(0)
                        combined_score = min(float(score1), float(score2))
                        # Validate digit count against known ERP SKU lengths.
                        # VR code = "VR" + N digits. len("VR") = 2.
                        digit_count = len(combined_code) - 2
                        # Trust the stitch only when digit count is unambiguously valid.
                        is_trusted = digit_count in _TRUSTED_VR_DIGIT_LENGTHS
                        substituted = not is_trusted
                        logger.debug(
                            "Crease stitch hit: %s + %s -> %s (conf: %.3f, trusted: %s)",
                            prefix_code, digits, combined_code, combined_score, is_trusted
                        )
                        stitched.append((combined_code, combined_score, substituted))
        except Exception as e:
            logger.debug("Error in box stitching pass: %s", e)
    return stitched


def _rotate(image, angle: int):
    if angle == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if angle == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if angle == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def _settled(candidates: list[Candidate]) -> bool:
    """A clean, high-confidence read with nothing disagreeing with it."""
    strong = [c for c in candidates
              if c.confidence >= OCR_EARLY_EXIT_CONFIDENCE and not c.substituted]
    if not strong:
        return False
    return len({c.code for c in strong}) == 1


def _ocr_single_pass(engine, image, angle: int, source: str) -> list[Candidate]:
    """Execute OCR on a single orientation pass."""
    found: list[Candidate] = []
    try:
        rotated = _rotate(image, angle) if angle != 0 else image
        ocr_result, _ = engine(rotated)
    except Exception as e:
        logger.debug("OCR engine error at %s rot%d: %s", source, angle, type(e).__name__)
        return found

    if not ocr_result:
        return found

    # 1. Direct per-line / token extraction
    for line in ocr_result:
        if len(line) < 3:
            continue
        text, score = line[1], line[2]
        hits = _extract(text)
        for code, substituted in hits:
            found.append(Candidate(code, float(score), "ocr", source, angle, substituted))

    # 2. Check for stitched crease boxes (e.g. VR1738 + 73)
    stitched_hits = _stitch_crease_boxes(ocr_result)
    for code, score, substituted in stitched_hits:
        if not any(c.code == code and c.rotation == angle for c in found):
            found.append(Candidate(code, score, "ocr", source, angle, substituted))

    # 3. Whole-result concatenation fallback for multiline splits
    valid_lines = [line[1] for line in ocr_result if len(line) >= 2]
    joined = " ".join(valid_lines)
    hits = _extract(joined)
    for code, substituted in hits:
        if not any(c.code == code and c.rotation == angle for c in found):
            scores = [float(line[2]) for line in ocr_result if len(line) >= 3] or [0.0]
            # Use the actual substituted flag from _extract; do NOT hard-code True.
            found.append(Candidate(code, min(scores), "ocr", source, angle, substituted))

    return found


def scan_ocr(image, roi_image=None, source: str = "full") -> list[Candidate]:
    """
    Tiered fast OCR scanner.
    Fast-path:
      1. Primary ROI / crop @ 0° -> if clean candidate found >= threshold, early-exits in <0.4s!
      2. If not settled, tries ROI rotations (180°, 90°, 270°).
      3. Fallback: full image @ 0°, then full image rotations. Skipped when
         `roi_image` is the exact same array as `image` (the pipeline's
         label-crop call pattern) — step 1 already scanned it at every
         orientation, so step 3 would repeat identical passes on identical
         pixels. Measured: this was doubling OCR time on every crop that did
         not settle immediately (25 forward passes / 13.5s for one image that
         should have taken 13 passes / ~7s).
    """
    engine = ocr_pool.acquire()
    candidates: list[Candidate] = []
    # Captured before roi_image is reassigned below by the resize step.
    roi_is_same_object_as_image = roi_image is image
    try:
        target_w = ROI_TARGET_WIDTH

        # Step 1: Evaluate Label ROI first
        if roi_image is not None:
            h, w = roi_image.shape[:2]
            if w > 0 and max(h, w) < target_w:
                scale = target_w / max(h, w)
                roi_image = cv2.resize(
                    roi_image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC
                )

            # 1a. Fast upright pass on ROI (0°)
            roi_0 = _ocr_single_pass(engine, roi_image, 0, "roi")
            candidates.extend(roi_0)
            if _settled(candidates):
                logger.debug("Fast-exit: Settled on ROI @ 0° (%s)", candidates[0].code)
                return candidates

            # 1b. Orientation sweeps on ROI if 0° did not settle
            for angle in (180, 90, 270):
                candidates.extend(_ocr_single_pass(engine, roi_image, angle, "roi"))
                if _settled(candidates):
                    logger.debug("Settled on ROI @ %d° (%s)", angle, candidates[0].code)
                    return candidates

        if roi_is_same_object_as_image:
            # Nothing left to learn from re-scanning the identical pixels.
            return candidates

        # Step 2: Prepare base image (upscale if small crop)
        h_img, w_img = image.shape[:2]
        if max(h_img, w_img) < target_w and min(h_img, w_img) > 0:
            scale = target_w / max(h_img, w_img)
            image = cv2.resize(
                image, (int(w_img * scale), int(h_img * scale)), interpolation=cv2.INTER_CUBIC
            )

        # Step 3: Base image scan (0° first)
        full_0 = _ocr_single_pass(engine, image, 0, source)
        candidates.extend(full_0)
        if _settled(candidates):
            logger.debug("Settled on Base Image @ 0° (%s)", candidates[0].code)
            return candidates

        for angle in (180, 90, 270):
            candidates.extend(_ocr_single_pass(engine, image, angle, source))
            if _settled(candidates):
                return candidates

    except Exception as e:
        logger.error("OCR processing error: %s", type(e).__name__)
    finally:
        ocr_pool.release(engine)

    return candidates
