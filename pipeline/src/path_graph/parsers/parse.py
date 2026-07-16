"""Document parsers — PDF pymupdf4llm JSON; Office/text blocks; HWP JSON."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from path_graph.parsers.adapters.unstructured import blocks_from_unstructured_elements
from path_graph.parsers.blocks_contract import normalize_blocks_document
from path_graph.parsers.route import (
    ParseBackend,
    UnsupportedFormatError,
    route_parse,
)

__all__ = [
    "UnsupportedFormatError",
    "parse_document",
    "parse_hwp_json",
    "parse_pdf_to_json",
    "parse_office_to_blocks",
    "parse_text_to_blocks",
    "parse_non_pdf_to_blocks",
]


def parse_hwp_json(data: bytes, rhwp_bin: str = "rhwp-batch") -> dict:
    tmp_in = Path("/tmp/path-graph-in.hwp")
    tmp_out = Path("/tmp/path-graph-out.json")
    tmp_in.write_bytes(data)
    try:
        subprocess.run(
            [rhwp_bin, "to-json", str(tmp_in), "-o", str(tmp_out), "--log-format=json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(tmp_out.read_text(encoding="utf-8"))
    finally:
        tmp_in.unlink(missing_ok=True)
        tmp_out.unlink(missing_ok=True)


def parse_pdf_to_json(data: bytes) -> dict:
    """Digital PDF → pymupdf4llm ``to_json()`` document (stored as-is in content.json)."""
    import pymupdf4llm

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        return json.loads(pymupdf4llm.to_json(tmp.name))


def parse_text_to_blocks(data: bytes) -> dict:
    """Plain ``.txt`` / ``.md`` → paragraph blocks (no markitdown)."""
    text = data.decode("utf-8", errors="replace").strip()
    blocks: list[dict] = []
    if text:
        for para in text.split("\n\n"):
            body = para.strip()
            if body:
                blocks.append(
                    {"type": "paragraph", "text": body, "heading_path": []}
                )
    return normalize_blocks_document({"blocks": blocks}, extractor="text")


def _element_as_mapping(el: object) -> dict:
    if hasattr(el, "to_dict"):
        raw = el.to_dict()  # type: ignore[operator]
        if isinstance(raw, dict):
            return raw
    return {
        "type": getattr(el, "category", None) or type(el).__name__,
        "text": getattr(el, "text", "") or "",
        "metadata": getattr(getattr(el, "metadata", None), "to_dict", lambda: {})(),
    }


def parse_office_to_blocks(data: bytes, filename: str) -> dict:
    """Office OOXML/BIFF → Unstructured elements → blocks."""
    suffix = Path(filename).suffix.lower() or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        if suffix == ".docx":
            from unstructured.partition.docx import partition_docx

            elements = partition_docx(filename=tmp.name)
        elif suffix == ".pptx":
            from unstructured.partition.pptx import partition_pptx

            elements = partition_pptx(filename=tmp.name)
        elif suffix in {".xlsx", ".xls"}:
            from unstructured.partition.xlsx import partition_xlsx

            elements = partition_xlsx(filename=tmp.name)
        else:
            raise UnsupportedFormatError(f"office extension {suffix} is not supported")
    mapped = [_element_as_mapping(el) for el in elements]
    return blocks_from_unstructured_elements(mapped)


def parse_non_pdf_to_blocks(
    data: bytes,
    filename: str,
    *,
    rhwp_bin: str = "rhwp-batch",
) -> dict:
    """Route non-PDF bytes to native blocks (HWP / Office / text)."""
    backend = route_parse(filename)
    if backend is ParseBackend.PYMUPDF:
        raise ValueError("PDF must use parse_pdf_to_json / ingest PDF path")
    if backend is ParseBackend.RHWP_BATCH:
        return normalize_blocks_document(
            parse_hwp_json(data, rhwp_bin=rhwp_bin),
            extractor="rhwp_batch",
        )
    if backend is ParseBackend.UNSTRUCTURED:
        return parse_office_to_blocks(data, filename)
    if backend is ParseBackend.TEXT:
        return parse_text_to_blocks(data)
    raise UnsupportedFormatError(f"unsupported backend {backend}")


def parse_document(
    data: bytes,
    filename: str,
    *,
    rhwp_bin: str = "rhwp-batch",
) -> tuple[str, dict | None]:
    """Compatibility wrapper — prefer ``parse_non_pdf_to_blocks``.

    Returns ``("", blocks_doc)`` for native paths. HWP also exposes raw JSON as
    the second value historically; callers should use blocks via
    ``parse_non_pdf_to_blocks``.
    """
    backend = route_parse(filename)
    if backend is ParseBackend.RHWP_BATCH:
        doc_json = parse_hwp_json(data, rhwp_bin=rhwp_bin)
        return json.dumps(doc_json, ensure_ascii=False), doc_json
    blocks = parse_non_pdf_to_blocks(data, filename, rhwp_bin=rhwp_bin)
    return "", blocks
