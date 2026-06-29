"""LangGraph workflow: graph context → wiki page."""

from __future__ import annotations

import json
from typing import Any, TypedDict

from wiki_synthesizer.artifact_io import fetch_bytes, read_json_bytes
from wiki_synthesizer.llm_json import parse_json_object
from wiki_synthesizer.paths import read_prompt

try:
    from runtime_common.providers.langgraph import prepare_langgraph_llm
except ImportError:

    def prepare_langgraph_llm(cfg: dict) -> Any:  # type: ignore[misc]
        raise RuntimeError("runtime_common.providers.langgraph not available")


class WikiState(TypedDict, total=False):
    tenant: str
    project_id: str
    project_slug: str
    community_id: str
    community_level: int
    graph_context_s3: str
    graph_context_text: str
    pages: list[dict]


def _wiki_slug(project_slug: str, level: int, community_id: str) -> str:
    short = community_id.replace("-", "")[:8]
    return f"{project_slug}-community-L{level}-{short}"


async def load_context(state: WikiState) -> dict:
    uri = state.get("graph_context_s3") or ""
    raw = fetch_bytes(uri)
    ctx = read_json_bytes(raw)
    return {"graph_context_text": json.dumps(ctx, ensure_ascii=False, indent=2)}


async def synthesize_page(state: WikiState, llm: Any) -> dict:
    from langchain_core.messages import HumanMessage

    template = read_prompt("community_report.txt")
    context_text = state.get("graph_context_text") or ""
    prompt = template.replace("{graph_context}", context_text)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    content = response.content if hasattr(response, "content") else str(response)
    data = parse_json_object(content)

    project_slug = state.get("project_slug") or "project"
    level = int(state.get("community_level") or 0)
    community_id = state.get("community_id") or ""
    slug = data.get("slug") or _wiki_slug(project_slug, level, community_id)
    page = {
        "slug": slug,
        "title": data.get("title") or slug,
        "markdown": data.get("markdown") or "",
    }
    return {
        "pages": [page],
        "tenant": state.get("tenant"),
        "project_id": state.get("project_id"),
    }


def build_graph(cfg: dict, secrets: Any) -> Any:
    from langgraph.graph import END, START, StateGraph

    _ = secrets
    llm = prepare_langgraph_llm(cfg)

    async def load_node(state: WikiState) -> dict:
        return await load_context(state)

    async def synthesize_node(state: WikiState) -> dict:
        return await synthesize_page(state, llm)

    builder = StateGraph(WikiState)
    builder.add_node("load", load_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_edge(START, "load")
    builder.add_edge("load", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile()
