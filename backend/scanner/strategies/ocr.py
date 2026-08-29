from __future__ import annotations
import cv2
import re
import logging
from core.config import OCR_EARLY_EXIT_CONFIDENCE
from scanner.engine_pool import ocr_pool
from scanner.result import Candidate

logger = logging.getLogger("vr-saree-sorter.strategies.ocr")

# VR immediately followed by 4-8 digits, and not more digits (not VRP, VRS...).
VR_RX = re.compile(r"VR\d{4,8}(?!\d)")

# Characters OCR routinely confuses with digits. Applying this map can rescue a
# genuine read — and can equally manufacture a plausible-looking code out of a
# misread. Matches that only appear after substitution are flagged so they can
# be sent to a human instead of silently renaming a file.
_DIGIT_MAP = str.maketrans("OoIl|", "00111")


def _normalise(text: str, substitute: bool) -> str:
    clean = text.replace(" ", "").upper()
    # Common OCR misread: '/' or '\' seen instead of 'V' before 'R'.
    clean = re.sub(r"[/\\]R(\d)", r"VR\1", clean)
    if substitute:
        clean = clean.translate(_DIGIT_MAP)
    return re.sub(r"[^A-Z0-9]", "", clean)


def _extract(text: str) -> tuple[str, bool] | None:
    """Return (code, substituted) or None."""
    strict = VR_RX.search(_normalise(text, substitute=False))
    loose = VR_RX.search(_normalise(text, substitute=True))
    if strict:
        # A strict match is trustworthy; note if substitution disagrees with it.
        return strict.group(0), bool(loose and loose.group(0) != strict.group(0))
    if loose:
        return loose.group(0), True
    return None


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
    return len({c.code for c in candidates}) == 1


def _ocr_candidates(engine, image, source: str) -> list[Candidate]:
    """
    Read one image across orientations and return every VR code seen.

    Rotations continue until a read is settled — high confidence, no character
    substitution, nothing disagreeing. Weaker reads keep sweeping so that the
    agreement check downstream has more than one pass to work with. 90/270 are
    not optional: labels photographed sideways are invisible to an upright pass.
    """
    found: list[Candidate] = []
    for angle in (0, 180, 90, 270):
        try:
            ocr_result, _ = engine(_rotate(image, angle))
        except Exception as e:
            logger.debug("OCR engine error at %s rot%d: %s", source, angle, type(e).__name__)
            continue
        if not ocr_result:
            continue

        for _, text, score in ocr_result:
            hit = _extract(text)
            if hit:
                code, substituted = hit
                found.append(Candidate(code, float(score), "ocr", source, angle, substituted))

        # Codes split across two detected lines ("VR" | "226941") only survive
        # concatenation. Scored conservatively: joining text loses the
        # per-line confidence, so take the weakest line involved.
        joined = " ".join(line[1] for line in ocr_result)
        hit = _extract(joined)
        if hit and not any(c.code == hit[0] and c.rotation == angle for c in found):
            scores = [float(line[2]) for line in ocr_result] or [0.0]
            found.append(Candidate(hit[0], min(scores), "ocr", source, angle, True))

        if _settled(found):
            logger.debug("Settled on %s at %s rot%d", found[0].code, source, angle)
            return found

    return found


def scan_ocr(image, roi_image=None) -> list[Candidate]:
    """Read the ROI and the full frame, returning every candidate from both."""
    engine = ocr_pool.acquire()
    candidates: list[Candidate] = []
    try:
        sources = []
        if roi_image is not None:
            h, w = roi_image.shape[:2]
            if w < 1200 and w > 0:
                scale = 1200 / w
                roi_image = cv2.resize(
                    roi_image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC
                )
            sources.append(("roi", roi_image))
        sources.append(("full", image))

        for name, img in sources:
            candidates.extend(_ocr_candidates(engine, img, name))
            if _settled(candidates):
                break
    except Exception as e:
        logger.error("OCR processing error: %s", type(e).__name__)
    finally:
        ocr_pool.release(engine)

    return candidates
