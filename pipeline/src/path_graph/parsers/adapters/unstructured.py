"""Unstructured typed elements → content.json blocks (#293)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from path_graph.parsers.blocks_contract import normalize_blocks_document

_SKIP_TYPES = frozenset(
    {
        "Header",
        "Footer",
        "PageBreak",
        "PageNumber",
    }
)


def _element_type(el: Mapping[str, Any]) -> str:
    raw = el.get("type") or el.get("category") or "NarrativeText"
    return str(raw)


def _meta_dict(el: Mapping[str, Any]) -> dict[str, Any]:
    meta = el.get("metadata")
    return dict(meta) if isinstance(meta, Mapping) else {}


def _bbox_from_coordinates(coords: Any) -> list[float] | None:
    if not isinstance(coords, Mapping):
        return None
    points = coords.get("points")
    if not isinstance(points, Sequence) or not points:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for pt in points:
        if isinstance(pt, Sequence) and len(pt) >= 2:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
    if not xs or not ys:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _block_metadata(meta: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    page = meta.get("page_number")
    if page is not None:
        out["page"] = int(page)
    bbox = _bbox_from_coordinates(meta.get("coordinates"))
    if bbox is not None:
        out["bbox"] = bbox
    return out


def _map_type(etype: str) -> str | None:
    if etype in _SKIP_TYPES:
        return None
    if etype == "Title":
        return "heading"
    if etype == "ListItem":
        return "list_item"
    if etype == "Table":
        return "table"
    if etype == "Image":
        return "image"
    if etype == "FigureCaption":
        return "figure_caption"
    return "paragraph"


def blocks_from_unstructured_elements(elements: Sequence[Mapping[str, Any]]) -> dict:
    """Convert Unstructured partition elements (dict form) to blocks document."""
    blocks: list[dict[str, Any]] = []
    heading_stack: list[str] = []

    for el in elements:
        etype = _element_type(el)
        mapped = _map_type(etype)
        if mapped is None:
            continue

        text = str(el.get("text") or "").strip()
        meta = _meta_dict(el)
        metadata = _block_metadata(meta)

        if mapped == "figure_caption":
            if blocks and blocks[-1].get("type") == "image" and text:
                blocks[-1]["caption"] = text
            elif text:
                block: dict[str, Any] = {
                    "type": "paragraph",
                    "text": text,
                    "heading_path": list(heading_stack),
                }
                if metadata:
                    block["metadata"] = metadata
                blocks.append(block)
            continue

        if mapped == "heading":
            if text:
                heading_stack = [text]
            block = {
                "type": "heading",
                "text": text,
                "heading_path": list(heading_stack),
            }
            if metadata:
                block["metadata"] = metadata
            blocks.append(block)
            continue

        if mapped == "table":
            html = meta.get("text_as_html")
            markdown = str(html).strip() if html else text
            if not markdown:
                continue
            block = {
                "type": "table",
                "markdown": markdown,
                "heading_path": list(heading_stack),
            }
            if metadata:
                block["metadata"] = metadata
            blocks.append(block)
            continue

        if mapped == "image":
            block = {
                "type": "image",
                "caption": text,
                "heading_path": list(heading_stack),
            }
            if metadata:
                block["metadata"] = metadata
            blocks.append(block)
            continue

        if not text:
            continue
        block = {
            "type": mapped,
            "text": text,
            "heading_path": list(heading_stack),
        }
        if metadata:
            block["metadata"] = metadata
        blocks.append(block)

    return normalize_blocks_document({"blocks": blocks}, extractor="unstructured")
