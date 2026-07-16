"""Import smoke for native parse stack (Docker/deps gate)."""

from __future__ import annotations


def test_native_parse_imports():
    import fitz  # noqa: F401
    import pymupdf4llm  # noqa: F401
    from unstructured.partition.docx import partition_docx  # noqa: F401

    from path_graph.parsers.image_caption import enrich_image_block_captions  # noqa: F401
    from path_graph.parsers.parse import (  # noqa: F401
        parse_non_pdf_to_blocks,
        parse_office_to_blocks,
        parse_pdf_to_json,
    )
    from path_graph.parsers.pdf_metrics import classify_pdf  # noqa: F401
