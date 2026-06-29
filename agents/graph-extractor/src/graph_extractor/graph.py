"""LangGraph workflow: chunks S3 → entity/edge extraction."""

from __future__ import annotations

from typing import Any, TypedDict

from graph_extractor.artifact_io import fetch_bytes, read_jsonl_bytes
from graph_extractor.llm_json import parse_json_object
from graph_extractor.paths import read_prompt

try:
    from runtime_common.providers.langgraph import prepare_langgraph_llm
except ImportError:  # local tests without agents-runtime checkout

    def prepare_langgraph_llm(cfg: dict) -> Any:  # type: ignore[misc]
        raise RuntimeError("runtime_common.providers.langgraph not available")


MAX_CHUNK_CHARS = 16_000


class GraphState(TypedDict, total=False):
    tenant: str
    project_id: str
    batch_id: str
    chunks_s3: str
    chunks_text: str
    entities: list[dict]
    edges: list[dict]


async def load_chunks(state: GraphState) -> dict:
    uri = state.get("chunks_s3") or ""
    raw = fetch_bytes(uri)
    lines = read_jsonl_bytes(raw)
    parts: list[str] = []
    total = 0
    for line in lines:
        text = (line.get("text") or "").strip()
        if not text:
            continue
        if total + len(text) > MAX_CHUNK_CHARS:
            break
        parts.append(text)
        total += len(text)
    return {"chunks_text": "\n\n".join(parts)}


async def extract_graph(state: GraphState, llm: Any) -> dict:
    from langchain_core.messages import HumanMessage

    template = read_prompt("extract_graph.txt")
    chunks_text = state.get("chunks_text") or ""
    prompt = template.replace("{chunks}", chunks_text)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    content = response.content if hasattr(response, "content") else str(response)
    data = parse_json_object(content)
    return {
        "entities": list(data.get("entities") or []),
        "edges": list(data.get("edges") or []),
    }


def build_graph(cfg: dict, secrets: Any) -> Any:
    from langgraph.graph import END, START, StateGraph

    _ = secrets
    llm = prepare_langgraph_llm(cfg)

    async def load_node(state: GraphState) -> dict:
        return await load_chunks(state)

    async def extract_node(state: GraphState) -> dict:
        return await extract_graph(state, llm)

    builder = StateGraph(GraphState)
    builder.add_node("load", load_node)
    builder.add_node("extract", extract_node)
    builder.add_edge(START, "load")
    builder.add_edge("load", "extract")
    builder.add_edge("extract", END)
    return builder.compile()
