"""LangGraph workflow: chunks S3 → entity/edge extraction."""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from graph_extractor.artifact_io import fetch_bytes, read_jsonl_bytes
from graph_extractor.batching import (
    DEFAULT_CHUNKS_PER_GROUP,
    DEFAULT_MAX_BATCH_CHARS,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_MAX_CONCURRENT_WORKERS,
    DEFAULT_MIN_SPLIT_CHARS,
    is_length_limit_error,
    is_splittable_extraction_error,
    merge_graph_parts,
    resolve_graph_extractor_budgets,
    split_chunk_batches,
    split_chunk_line_groups,
    split_batch_text,
)
from graph_extractor.llm_json import invoke_json_llm
from graph_extractor.text_sanitize import ensure_json_utf8_safe, sanitize_graph_v1
from graph_extractor.output_schema import graph_v1_response_format
from graph_extractor.paths import read_prompt

try:
    from runtime_common.providers.langgraph import prepare_langgraph_llm
except ImportError:  # local tests without agents-runtime checkout

    def prepare_langgraph_llm(cfg: dict) -> Any:  # type: ignore[misc]
        raise RuntimeError("runtime_common.providers.langgraph not available")


class GraphState(TypedDict, total=False):
    tenant: str
    project_id: str
    batch_id: str
    chunks_s3: str
    chunk_groups: list[list[str]]
    chunk_batches: list[str]
    chunks_text: str
    entities: list[dict]
    edges: list[dict]


def _graph_extractor_cfg(cfg: dict) -> dict:
    return cfg.get("graph_extractor") or {}


async def load_chunks(
    state: GraphState,
    *,
    max_batch_chars: int = DEFAULT_MAX_BATCH_CHARS,
    chunks_per_group: int = DEFAULT_CHUNKS_PER_GROUP,
) -> dict:
    uri = state.get("chunks_s3") or ""
    raw = fetch_bytes(uri)
    lines = read_jsonl_bytes(raw)
    line_groups = split_chunk_line_groups(
        lines,
        max_chunks_per_group=chunks_per_group,
    )
    chunk_groups = [
        split_chunk_batches(group_lines, max_batch_chars=max_batch_chars)
        for group_lines in line_groups
    ]
    batches = [batch for group in chunk_groups for batch in group]
    payload = {
        "chunk_groups": chunk_groups,
        "chunk_batches": batches,
        "chunks_text": "\n\n".join(batches),
    }
    ensure_json_utf8_safe(payload)
    return payload


async def _extract_chunks_text(
    chunks_text: str,
    *,
    llm: Any,
    template: str,
    response_format: dict,
    max_completion_tokens: int,
    min_split_chars: int,
) -> dict:
    prompt = template.replace("{chunks}", chunks_text)
    try:
        return await invoke_json_llm(
            llm,
            prompt,
            response_format=response_format,
            max_tokens=max_completion_tokens,
        )
    except Exception as exc:
        if not is_splittable_extraction_error(exc):
            raise
        if len(chunks_text) <= min_split_chars:
            return {"entities": [], "edges": []}
        left, right = split_batch_text(chunks_text)
        if not left or not right:
            raise
        left_result, right_result = await asyncio.gather(
            _extract_chunks_text(
                left,
                llm=llm,
                template=template,
                response_format=response_format,
                max_completion_tokens=max_completion_tokens,
                min_split_chars=min_split_chars,
            ),
            _extract_chunks_text(
                right,
                llm=llm,
                template=template,
                response_format=response_format,
                max_completion_tokens=max_completion_tokens,
                min_split_chars=min_split_chars,
            ),
        )
        return merge_graph_parts([left_result, right_result])


async def extract_graph(
    state: GraphState,
    llm: Any,
    *,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    min_split_chars: int = DEFAULT_MIN_SPLIT_CHARS,
    max_concurrent_workers: int = DEFAULT_MAX_CONCURRENT_WORKERS,
) -> dict:
    template = read_prompt("extract_graph.txt")
    chunk_groups = list(state.get("chunk_groups") or [])
    if not chunk_groups:
        batches = list(state.get("chunk_batches") or [])
        if not batches:
            text = (state.get("chunks_text") or "").strip()
            batches = [text] if text else []
        if batches:
            chunk_groups = [batches]

    response_format = graph_v1_response_format()
    sem = asyncio.Semaphore(max(1, max_concurrent_workers))
    parts: list[dict] = []

    async def run_batch(chunks_text: str) -> dict:
        async with sem:
            return await _extract_chunks_text(
                chunks_text,
                llm=llm,
                template=template,
                response_format=response_format,
                max_completion_tokens=max_completion_tokens,
                min_split_chars=min_split_chars,
            )

    for group_batches in chunk_groups:
        tasks = [run_batch(batch) for batch in group_batches if batch.strip()]
        if tasks:
            group_parts = await asyncio.gather(*tasks)
            parts.extend(group_parts)

    merged = sanitize_graph_v1(merge_graph_parts(parts))
    payload = {
        "entities": list(merged.get("entities") or []),
        "edges": list(merged.get("edges") or []),
    }
    ensure_json_utf8_safe(payload)
    return payload


def build_graph(cfg: dict, secrets: Any) -> Any:
    from langgraph.graph import END, START, StateGraph

    _ = secrets
    llm = prepare_langgraph_llm(cfg)
    graph_cfg = _graph_extractor_cfg(cfg)
    preset_batch, preset_completion = resolve_graph_extractor_budgets(cfg)
    max_batch_chars = int(graph_cfg.get("max_batch_chars", preset_batch))
    max_completion_tokens = int(
        graph_cfg.get("max_completion_tokens", preset_completion)
    )
    min_split_chars = int(graph_cfg.get("min_split_chars", DEFAULT_MIN_SPLIT_CHARS))
    chunks_per_group = int(graph_cfg.get("chunks_per_group", DEFAULT_CHUNKS_PER_GROUP))
    max_concurrent_workers = int(
        graph_cfg.get("max_concurrent_workers", DEFAULT_MAX_CONCURRENT_WORKERS)
    )

    async def load_node(state: GraphState) -> dict:
        return await load_chunks(
            state,
            max_batch_chars=max_batch_chars,
            chunks_per_group=chunks_per_group,
        )

    async def extract_node(state: GraphState) -> dict:
        return await extract_graph(
            state,
            llm,
            max_completion_tokens=max_completion_tokens,
            min_split_chars=min_split_chars,
            max_concurrent_workers=max_concurrent_workers,
        )

    builder = StateGraph(GraphState)
    builder.add_node("load", load_node)
    builder.add_node("extract", extract_node)
    builder.add_edge(START, "load")
    builder.add_edge("load", "extract")
    builder.add_edge("extract", END)
    return builder.compile()
