from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Method = Literal["barcode", "ocr", "none"]


@dataclass(frozen=True)
class Candidate:
    """One VR code the scanner extracted, with how it was obtained."""

    code: str
    confidence: float
    method: Method
    source: str = ""          # "roi" / "full" / "crop2" — which image was read
    rotation: int = 0         # degrees the image was rotated before reading
    substituted: bool = False # matched only after O->0 / I->1 character fixes


@dataclass(frozen=True)
class ScanResult:
    """
    Outcome of scanning a single image.

    The distinction that matters operationally is between `code is None`
    (nothing found — the image goes to the failed pile) and `needs_review`
    (something was found but it is not trustworthy enough to rename a file
    with). A wrong rename is silent and permanent; a review is cheap.
    """

    code: str | None = None
    confidence: float = 0.0
    method: Method = "none"
    needs_review: bool = False
    reason: str = ""
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)

    @property
    def is_confident(self) -> bool:
        """True only when the code can be used to rename a file unattended."""
        return self.code is not None and not self.needs_review

    def __bool__(self) -> bool:
        # Keeps `if result:` working for callers that only care whether
        # anything at all was extracted.
        return self.code is not None
