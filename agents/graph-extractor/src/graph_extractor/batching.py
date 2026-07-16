"""Split chunks and merge graph extraction results."""

from __future__ import annotations

import os

DEFAULT_MAX_BATCH_CHARS = 4_000
DEFAULT_MAX_COMPLETION_TOKENS = 4_096
DEFAULT_MIN_SPLIT_CHARS = 400
DEFAULT_CHUNKS_PER_GROUP = 100
DEFAULT_MAX_CONCURRENT_WORKERS = 2
PROMPT_OVERHEAD_TOKENS = 3_500
CHARS_PER_TOKEN = 3.5


def compute_graph_extractor_budgets(
    context_window_tokens: int,
    max_output_tokens: int | None = None,
) -> tuple[int, int]:
    """Derive batch/completion ceilings from a preset context window."""
    completion = max_output_tokens or min(8_192, context_window_tokens // 2)
    completion = min(completion, context_window_tokens - PROMPT_OVERHEAD_TOKENS - 256)
    input_tokens = max(256, context_window_tokens - completion - PROMPT_OVERHEAD_TOKENS)
    max_batch_chars = max(500, int(input_tokens * CHARS_PER_TOKEN))
    return max_batch_chars, max(completion, 256)


def _read_preset_limits(preset_name: str) -> tuple[int | None, int | None]:
    try:
        from runtime_common.providers.langgraph import read_llm_preset_limits

        return read_llm_preset_limits(preset_name)
    except ImportError:
        prefix = f"LLM_PRESET_{preset_name}"
        ctx_raw = os.environ.get(f"{prefix}_CONTEXT_WINDOW", "").strip()
        out_raw = os.environ.get(f"{prefix}_MAX_OUTPUT_TOKENS", "").strip()
        context = int(ctx_raw) if ctx_raw else None
        max_output = int(out_raw) if out_raw else None
        return context, max_output


def _extract_preset_name(model_spec: str | None) -> str | None:
    try:
        from runtime_common.providers.langgraph import extract_preset_name

        return extract_preset_name(model_spec)
    except ImportError:
        if model_spec and model_spec.startswith("preset:"):
            name = model_spec[len("preset:") :].strip()
            return name or None
        return None


def resolve_graph_extractor_budgets(cfg: dict) -> tuple[int, int]:
    """Resolve default batch/completion budgets from preset env or conservative fallback."""
    model_spec = (cfg.get("langgraph") or {}).get("model")
    preset = _extract_preset_name(model_spec)
    if preset:
        context_window, max_output = _read_preset_limits(preset)
        if context_window:
            return compute_graph_extractor_budgets(context_window, max_output)
    return DEFAULT_MAX_BATCH_CHARS, DEFAULT_MAX_COMPLETION_TOKENS


def is_length_limit_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "length limit" in message or "lengthfinishreason" in message


def is_empty_json_error(exc: BaseException) -> bool:
    import json

    return isinstance(exc, json.JSONDecodeError) and "expecting value" in str(exc).lower()


def is_splittable_extraction_error(exc: BaseException) -> bool:
    return is_length_limit_error(exc) or is_empty_json_error(exc)


def split_text_half(text: str) -> tuple[str, str]:
    """Last-resort character split (used when chunk/line boundaries are unavailable)."""
    stripped = text.strip()
    if not stripped:
        return "", ""
    midpoint = len(stripped) // 2
    breaks = [i for i in range(len(stripped)) if stripped.startswith("\n\n", i)]
    if breaks:
        split_at = min(breaks, key=lambda index: abs(index - midpoint))
    else:
        split_at = midpoint
    left = stripped[:split_at].strip()
    right = stripped[split_at:].strip()
    return left, right


def _split_joined_parts(parts: list[str], *, joiner: str, midpoint: int) -> tuple[str, str]:
    if len(parts) < 2:
        return "", ""
    cumulative = 0
    best_idx = 1
    best_distance = float("inf")
    for idx in range(1, len(parts)):
        cumulative += len(parts[idx - 1]) + len(joiner)
        distance = abs(cumulative - midpoint)
        if distance < best_distance:
            best_distance = distance
            best_idx = idx
    left = joiner.join(parts[:best_idx]).strip()
    right = joiner.join(parts[best_idx:]).strip()
    if left and right:
        return left, right
    return "", ""


def split_batch_text(text: str) -> tuple[str, str]:
    """Split LLM batch text without breaking joined chunk boundaries when possible."""
    stripped = text.strip()
    if not stripped:
        return "", ""
    midpoint = len(stripped) // 2

    if "\n\n" in stripped:
        left, right = _split_joined_parts(stripped.split("\n\n"), joiner="\n\n", midpoint=midpoint)
        if left and right:
            return left, right

    if "\n" in stripped:
        left, right = _split_joined_parts(stripped.split("\n"), joiner="\n", midpoint=midpoint)
        if left and right:
            return left, right

    return split_text_half(stripped)


def split_chunk_line_groups(
    lines: list[dict],
    *,
    max_chunks_per_group: int,
) -> list[list[dict]]:
    """Split non-empty chunk lines into fixed-size groups for sequential processing."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    for line in lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        current.append(line)
        if len(current) >= max_chunks_per_group:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def split_chunk_batches(lines: list[dict], *, max_batch_chars: int) -> list[str]:
    """Group chunk texts into batches that fit the LLM context budget."""
    from graph_extractor.text_sanitize import sanitize_chunk_text

    batches: list[str] = []
    parts: list[str] = []
    total = 0
    for line in lines:
        text = sanitize_chunk_text(line.get("text") or "")
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
    from graph_extractor.text_sanitize import sanitize_graph_v1

    entities: list[dict] = []
    edges: list[dict] = []
    seen_entity_ids: set[str] = set()
    seen_edge_keys: set[tuple] = set()
    for data in parts:
        cleaned = sanitize_graph_v1(data)
        for entity in cleaned.get("entities") or []:
            eid = str(entity.get("id") or entity.get("name") or "")
            if not eid or eid in seen_entity_ids:
                continue
            seen_entity_ids.add(eid)
            entities.append(entity)
        for edge in cleaned.get("edges") or []:
            key = (edge.get("type"), edge.get("source"), edge.get("target"))
            if key in seen_edge_keys:
                continue
            seen_edge_keys.add(key)
            edges.append(edge)
    merged = {"entities": entities, "edges": edges}
    return sanitize_graph_v1(merged)
