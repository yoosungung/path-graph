"""Split chunks and merge graph extraction results."""

from __future__ import annotations

DEFAULT_MAX_BATCH_CHARS = 2_500
DEFAULT_MAX_COMPLETION_TOKENS = 8_192
DEFAULT_MIN_SPLIT_CHARS = 400

_LENGTH_LIMIT_MARKERS = (
    "length limit was reached",
    "lengthfinishreasonerror",
)


def is_length_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _LENGTH_LIMIT_MARKERS)


def split_text_half(text: str) -> tuple[str, str]:
    """Split chunk text near the middle, preferring paragraph boundaries."""
    stripped = text.strip()
    if not stripped:
        return "", ""
    if len(stripped) < 2:
        return stripped, ""

    mid = len(stripped) // 2
    window_start = max(0, mid - 200)
    window = stripped[window_start : min(len(stripped), mid + 200)]
    para_idx = window.find("\n\n")
    if para_idx >= 0:
        split_at = window_start + para_idx + 2
        left = stripped[:split_at].strip()
        right = stripped[split_at:].strip()
        if left and right:
            return left, right

    left = stripped[:mid].strip()
    right = stripped[mid:].strip()
    return left, right


def split_chunk_batches(lines: list[dict], *, max_batch_chars: int) -> list[str]:
    """Group chunk texts into batches that fit the LLM context budget."""
    batches: list[str] = []
    parts: list[str] = []
    total = 0
    for line in lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        if parts and total + len(text) > max_batch_chars:
            batches.append("\n\n".join(parts))
            parts = []
            total = 0
        parts.append(text)
        total += len(text)
    if parts:
        batches.append("\n\n".join(parts))
    return batches


def merge_graph_parts(parts: list[dict]) -> dict:
    entities: list[dict] = []
    edges: list[dict] = []
    seen_entity_ids: set[str] = set()
    seen_edge_keys: set[tuple] = set()
    for data in parts:
        for entity in data.get("entities") or []:
            eid = str(entity.get("id") or entity.get("name") or "")
            if not eid or eid in seen_entity_ids:
                continue
            seen_entity_ids.add(eid)
            entities.append(entity)
        for edge in data.get("edges") or []:
            key = (edge.get("type"), edge.get("source"), edge.get("target"))
            if key in seen_edge_keys:
                continue
            seen_edge_keys.add(key)
            edges.append(edge)
    return {"entities": entities, "edges": edges}
