"""Native parser → content.json blocks adapters (#293 / #279)."""

from __future__ import annotations

from path_graph.parsers.adapters.pymupdf import blocks_from_pymupdf_page_chunks
from path_graph.parsers.adapters.unstructured import blocks_from_unstructured_elements

__all__ = [
    "blocks_from_pymupdf_page_chunks",
    "blocks_from_unstructured_elements",
]
