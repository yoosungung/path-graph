"""LangGraph workflow: chunks S3 → entity/edge extraction."""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from graph_extractor.artifact_io import fetch_bytes, read_jsonl_bytes
from graph_extractor.batching import (
    DEFAULT_MAX_BATCH_CHARS,
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_MIN_SPLIT_CHARS,
    is_length_limit_error,
    is_splittable_extraction_error,
    merge_graph_parts,
    resolve_graph_extractor_budgets,
    split_chunk_batches,
    split_text_half,
)
from graph_extractor.llm_json import invoke_json_llm
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
) -> dict:
    uri = state.get("chunks_s3") or ""
    raw = fetch_bytes(uri)
    lines = read_jsonl_bytes(raw)
    batches = split_chunk_batches(lines, max_batch_chars=max_batch_chars)
    return {
        "chunk_batches": batches,
        "chunks_text": "\n\n".join(batches),
    }


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
        left, right = split_text_half(chunks_text)
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
) -> dict:
    template = read_prompt("extract_graph.txt")
    batches = list(state.get("chunk_batches") or [])
    if not batches:
        text = (state.get("chunks_text") or "").strip()
        if text:
            batches = [text]

    response_format = graph_v1_response_format()
    parts: list[dict] = []
    for chunks_text in batches:
        if not chunks_text.strip():
            continue
        data = await _extract_chunks_text(
            chunks_text,
            llm=llm,
            template=template,
            response_format=response_format,
            max_completion_tokens=max_completion_tokens,
            min_split_chars=min_split_chars,
        )
        parts.append(data)

    merged = merge_graph_parts(parts)
    return {
        "entities": list(merged.get("entities") or []),
        "edges": list(merged.get("edges") or []),
    }


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

    async def load_node(state: GraphState) -> dict:
        return await load_chunks(state, max_batch_chars=max_batch_chars)

    async def extract_node(state: GraphState) -> dict:
        return await extract_graph(
            state,
            llm,
            max_completion_tokens=max_completion_tokens,
            min_split_chars=min_split_chars,
        )

    builder = StateGraph(GraphState)
    builder.add_node("load", load_node)
    builder.add_node("extract", extract_node)
    builder.add_edge(START, "load")
    builder.add_edge("load", "extract")
    builder.add_edge("extract", END)
    return builder.compile()
