from __future__ import annotations
import cv2
import numpy as np
import logging
from collections import defaultdict

from core.config import OCR_MIN_CONFIDENCE, OCR_EARLY_EXIT_CONFIDENCE, MAX_SCAN_DIMENSION
from scanner.result import Candidate, ScanResult
from scanner.utils import detect_label_regions
from scanner.strategies.barcode import decode_barcode_robust
from scanner.strategies.ocr import scan_ocr

logger = logging.getLogger("vr-saree-sorter.pipeline")

# Maximum number of label crops to scan before falling back to full-image OCR.
# Prevents one upload from triggering unbounded OCR work on image-heavy labels.
_MAX_LABEL_CROPS = 3


def _candidates_are_settled(candidates: list[Candidate]) -> bool:
    """True when candidates contain at least one clean, high-confidence read with consensus."""
    strong = [c for c in candidates
              if c.confidence >= OCR_EARLY_EXIT_CONFIDENCE and not c.substituted]
    if not strong:
        return False
    return len({c.code for c in strong}) == 1


def _candidates_are_weak(candidates: list[Candidate]) -> bool:
    """True when all candidates are low-confidence or required character substitution."""
    if not candidates:
        return True
    return all(c.confidence < OCR_MIN_CONFIDENCE or c.substituted for c in candidates)


def _decide(candidates: list[Candidate]) -> ScanResult:
    """
    Turn raw OCR candidates into a verdict.

    Renaming a file with the wrong code is silent and effectively permanent,
    so anything doubtful is routed to a human instead of guessed at. Three
    things disqualify an automatic rename:

      1. Low confidence. Correct reads on the sample set scored 0.944-0.998
         (median 0.996), so the 0.90 default floor has real headroom.
      2. Character substitution. A match that only appears after O->0 / I->1
         fixes may be a rescued read or an invented one; nothing in the text
         distinguishes them.
      3. Conflict. Two different codes both read confidently means at least
         one is wrong, and there is no basis for picking.
    """
    if not candidates:
        return ScanResult(method="none", reason="no VR code detected")

    best_by_code: dict[str, Candidate] = {}
    support: dict[str, set] = defaultdict(set)
    for c in candidates:
        support[c.code].add((c.source, c.rotation))
        if c.code not in best_by_code or c.confidence > best_by_code[c.code].confidence:
            best_by_code[c.code] = c

    # Deduplicate fragments: Remove a candidate only when its extraction metadata confirms
    # it is a fragment from the same OCR read (same source, rotation, and method);
    # otherwise retain both codes for the existing rival check to evaluate.
    filtered_by_code: dict[str, Candidate] = {}
    for code, cand in best_by_code.items():
        is_fragment = any(
            other.code != code
            and len(other.code) > len(code)
            and other.code.startswith(code)
            and other.source == cand.source
            and other.rotation == cand.rotation
            and other.method == cand.method
            for other in candidates
        )
        if not is_fragment:
            filtered_by_code[code] = cand

    # Rank: (1) not substituted, (2) >= 5 digits (length >= 7 with 'VR'), (3) confidence
    def _rank_key(c: Candidate):
        is_full_length = len(c.code) >= 7
        return (not c.substituted, is_full_length, c.confidence)

    ranked = sorted(filtered_by_code.values(), key=_rank_key, reverse=True)
    best = ranked[0]
    all_candidates = tuple(ranked)

    # Rivals check: prefer the longer code when candidates are in a prefix relation
    # from DIFFERENT sources; otherwise retain both as rivals for review.
    # A shorter higher-confidence read from a different source cannot silently
    # displace a longer conflicting code.
    rivals = []
    for c in ranked[1:]:
        if c.confidence < OCR_MIN_CONFIDENCE:
            continue
        if best.code.startswith(c.code) or c.code.startswith(best.code):
            # Prefix relation: only suppress the shorter code if it came from
            # the same source/rotation (i.e. the same OCR pass). Cross-source
            # prefix conflicts should surface for review.
            if c.source != best.source or c.rotation != best.rotation:
                rivals.append(c)
        else:
            rivals.append(c)

    if rivals:
        return ScanResult(
            code=best.code, confidence=best.confidence, method="ocr", needs_review=True,
            reason=f"conflicting reads: {best.code} ({best.confidence:.3f}) vs "
                   f"{rivals[0].code} ({rivals[0].confidence:.3f})",
            candidates=all_candidates,
        )

    if best.confidence < OCR_MIN_CONFIDENCE:
        return ScanResult(
            code=best.code, confidence=best.confidence, method="ocr", needs_review=True,
            reason=f"confidence {best.confidence:.3f} below {OCR_MIN_CONFIDENCE:.2f}",
            candidates=all_candidates,
        )

    if best.substituted:
        return ScanResult(
            code=best.code, confidence=best.confidence, method="ocr", needs_review=True,
            reason="matched only after O/I character substitution",
            candidates=all_candidates,
        )

    return ScanResult(
        code=best.code, confidence=best.confidence, method="ocr", needs_review=False,
        reason=f"agreed by {len(support[best.code])} pass(es)", candidates=all_candidates,
    )


def process_pipeline(image_bytes: bytes, max_dim: int | None = None) -> ScanResult:
    """
    Scan one image for its VR code. Never raises; failures come back as a ScanResult.

    `max_dim` overrides the working resolution. Retrying at a larger value is
    the one knob that makes a second attempt meaningful: the pipeline is
    otherwise deterministic, so re-running it unchanged always returns exactly
    the same answer.
    """
    limit = max_dim or MAX_SCAN_DIMENSION
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        original_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if original_image is None:
            logger.warning("Could not decode image bytes")
            return ScanResult(method="none", reason="undecodable image")

        h, w = original_image.shape[:2]
        if max(h, w) > limit:
            scale = limit / max(h, w)
            original_image = cv2.resize(
                original_image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
            )
    except Exception as e:
        logger.error("Image decoding error: %s", type(e).__name__)
        return ScanResult(method="none", reason=f"decode error: {type(e).__name__}")

    label_crops = detect_label_regions(original_image)
    logger.debug("Detected %d label regions", len(label_crops))

    # Barcodes first: Code128 and QR carry their own checksums, so a successful
    # decode is self-verifying and never needs review.
    for i, crop in enumerate(label_crops):
        code = decode_barcode_robust(crop)
        if code:
            logger.info("Barcode found on label crop %d: %s", i, code)
            return ScanResult(code=code, confidence=1.0, method="barcode",
                              reason="checksum-verified barcode",
                              candidates=(Candidate(code, 1.0, "barcode", f"crop{i}"),))

    code = decode_barcode_robust(original_image)
    if code:
        logger.info("Barcode found on full image scan: %s", code)
        return ScanResult(code=code, confidence=1.0, method="barcode",
                          reason="checksum-verified barcode",
                          candidates=(Candidate(code, 1.0, "barcode", "full"),))

    # OCR fallback: try detected label crops first (fast and highly accurate).
    # Pass each crop as roi_image so scan_ocr uses the tiered ROI fast-exit path.
    # Stop immediately on a settled, high-confidence read.
    # Cap at _MAX_LABEL_CROPS to bound OCR work per image.
    logger.debug("Attempting OCR fallback")
    candidates: list[Candidate] = []
    crops_scanned = 0
    if label_crops:
        for i, crop in enumerate(label_crops[:_MAX_LABEL_CROPS]):
            crop_candidates = scan_ocr(crop, roi_image=crop, source=f"crop{i}")
            crops_scanned += 1
            if crop_candidates:
                candidates.extend(crop_candidates)
                if _candidates_are_settled(candidates):
                    logger.debug("Settled on label crop %d", i)
                    break

    # Fall back to full-image OCR when:
    #   (a) no crops were found, OR
    #   (b) crop candidates exist but are all weak (low-confidence or substituted).
    # Strong crop results are preserved — we don't overwrite them.
    if not candidates or _candidates_are_weak(candidates):
        logger.debug("Crop candidates weak or absent; running full-image OCR")
        full_candidates = scan_ocr(original_image, source="full")
        candidates.extend(full_candidates)

    return _decide(candidates)
