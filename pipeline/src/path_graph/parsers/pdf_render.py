from __future__ import annotations

import fitz


def render_pdf_pages(data: bytes, *, dpi: int = 200) -> list[bytes]:
    """Render each PDF page to PNG bytes (PyMuPDF)."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        pages: list[bytes] = []
        for page in doc:
            pixmap = page.get_pixmap(dpi=dpi)
            pages.append(pixmap.tobytes("png"))
        return pages
    finally:
        doc.close()
