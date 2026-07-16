"""PDF page metrics for digital vs scan routing (#280).

Uses PyMuPDF only — text layer length and image coverage ratio.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import fitz


class PdfKind(StrEnum):
    DIGITAL = "digital"
    SCAN = "scan"


@dataclass(frozen=True, slots=True)
class PdfMetrics:
    page_count: int
    text_chars: int  # sum of stripped page text lengths
    image_ratio: float  # mean page image coverage

    @property
    def avg_text_chars(self) -> float:
        if self.page_count <= 0:
            return 0.0
        return self.text_chars / self.page_count


# Aligned with OCR_MIN_TEXT_CHARS default and DESIGN scan policy.
DEFAULT_MIN_TEXT_CHARS = 32
DEFAULT_MIN_IMAGE_RATIO = 0.5


def measure_pdf(data: bytes) -> PdfMetrics:
    """Aggregate text_chars / mean image_ratio / page_count over the PDF."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        page_count = doc.page_count
        if page_count == 0:
            return PdfMetrics(page_count=0, text_chars=0, image_ratio=0.0)

        total_chars = 0
        ratio_sum = 0.0
        for page in doc:
            total_chars += len((page.get_text("text") or "").strip())
            ratio_sum += _page_image_ratio(page)
        return PdfMetrics(
            page_count=page_count,
            text_chars=total_chars,
            image_ratio=ratio_sum / page_count,
        )
    finally:
        doc.close()


def classify_pdf(
    data: bytes,
    *,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
    min_image_ratio: float = DEFAULT_MIN_IMAGE_RATIO,
) -> PdfKind:
    """Scan when avg text is low AND image-heavy; otherwise digital."""
    metrics = measure_pdf(data)
    if (
        metrics.avg_text_chars < min_text_chars
        and metrics.image_ratio >= min_image_ratio
    ):
        return PdfKind.SCAN
    return PdfKind.DIGITAL


def _page_image_ratio(page: fitz.Page) -> float:
    page_area = abs(page.rect.width * page.rect.height)
    if page_area <= 0:
        return 0.0
    image_area = 0.0
    for img in page.get_images(full=True):
        xref = img[0]
        for rect in page.get_image_rects(xref):
            image_area += abs(rect.width * rect.height)
    # Cap at 1.0 — overlapping images can exceed page area.
    return min(1.0, image_area / page_area)
