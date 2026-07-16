"""Crop PDF image regions and fill captions via Vision API (#280)."""

from __future__ import annotations

from typing import Any

import fitz

from path_graph.config import Settings, get_settings
from path_graph.parsers.ocr_prompt import DEFAULT_CAPTION_PROMPT
from path_graph.parsers.pymupdf_json import box_bbox, is_pymupdf_json_document
from path_graph.parsers.vl_ocr import VlOcrClient


def crop_pdf_region_png(
    data: bytes,
    *,
    page: int,
    bbox: list[float],
    dpi: int = 200,
) -> bytes:
    """Render ``bbox`` on 1-based ``page`` to PNG bytes."""
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page}")
    if len(bbox) < 4:
        raise ValueError("bbox requires [x0, y0, x1, y1]")
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if page > doc.page_count:
            raise ValueError(f"page {page} out of range ({doc.page_count})")
        pdf_page = doc[page - 1]
        clip = fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        pixmap = pdf_page.get_pixmap(clip=clip, dpi=dpi)
        return pixmap.tobytes("png")
    finally:
        doc.close()


def _enrich_blocks_image_captions(
    blocks_doc: dict[str, Any],
    data: bytes,
    *,
    settings: Settings,
    client: VlOcrClient,
) -> dict[str, Any]:
    prompt = DEFAULT_CAPTION_PROMPT
    blocks = blocks_doc.get("blocks")
    if not isinstance(blocks, list):
        return blocks_doc

    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        if str(block.get("caption") or "").strip():
            continue
        meta = block.get("metadata")
        if not isinstance(meta, dict):
            continue
        page = meta.get("page")
        bbox = meta.get("bbox")
        if page is None or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        try:
            png = crop_pdf_region_png(
                data,
                page=int(page),
                bbox=[float(x) for x in bbox[:4]],
                dpi=settings.ocr_render_dpi,
            )
            caption = client.ocr_page_png(png, prompt=prompt).strip()
        except Exception:
            continue
        if caption:
            block["caption"] = caption

    return blocks_doc


def _enrich_pymupdf_json_image_captions(
    parsed_doc: dict[str, Any],
    data: bytes,
    *,
    settings: Settings,
    client: VlOcrClient,
) -> dict[str, Any]:
    prompt = DEFAULT_CAPTION_PROMPT
    pages = parsed_doc.get("pages")
    if not isinstance(pages, list):
        return parsed_doc

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_no = page.get("page_number")
        if page_no is None:
            continue
        boxes = page.get("boxes")
        if not isinstance(boxes, list):
            continue
        for box in boxes:
            if not isinstance(box, dict):
                continue
            boxclass = str(box.get("boxclass") or "").lower()
            if boxclass not in {"picture", "image"}:
                continue
            if str(box.get("caption") or "").strip():
                continue
            bbox = box_bbox(box)
            if bbox is None:
                continue
            try:
                png = crop_pdf_region_png(
                    data,
                    page=int(page_no),
                    bbox=bbox,
                    dpi=settings.ocr_render_dpi,
                )
                caption = client.ocr_page_png(png, prompt=prompt).strip()
            except Exception:
                continue
            if caption:
                box["caption"] = caption

    return parsed_doc


def enrich_image_block_captions(
    parsed_doc: dict[str, Any],
    data: bytes,
    *,
    settings: Settings | None = None,
    client: VlOcrClient | None = None,
) -> dict[str, Any]:
    """Fill empty image captions via crop → Vision, preserving document order."""
    settings = settings or get_settings()
    if not settings.ocr_llm_base_url.strip() or not settings.ocr_llm_model.strip():
        return parsed_doc

    ocr = client or VlOcrClient(settings)
    if is_pymupdf_json_document(parsed_doc):
        return _enrich_pymupdf_json_image_captions(
            parsed_doc,
            data,
            settings=settings,
            client=ocr,
        )
    return _enrich_blocks_image_captions(
        parsed_doc,
        data,
        settings=settings,
        client=ocr,
    )
