"""LangGraph workflow: graph context → wiki page."""

from __future__ import annotations

import json
from typing import Any, TypedDict

from wiki_synthesizer.artifact_io import fetch_bytes, read_json_bytes
from wiki_synthesizer.llm_json import invoke_json_llm
from wiki_synthesizer.output_schema import assemble_wiki_markdown, wiki_v1_response_format
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


async def load_context(state: WikiState) -> dict:
    uri = state.get("graph_context_s3") or ""
    raw = fetch_bytes(uri)
    ctx = read_json_bytes(raw)
    return {"graph_context_text": json.dumps(ctx, ensure_ascii=False, indent=2)}


DEFAULT_MAX_COMPLETION_TOKENS = 2048


async def synthesize_page(
    state: WikiState,
    llm: Any,
    *,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
) -> dict:
    template = read_prompt("community_report.txt")
    context_text = state.get("graph_context_text") or ""
    prompt = template.replace("{graph_context}", context_text)
    data = await invoke_json_llm(
        llm,
        prompt,
        response_format=wiki_v1_response_format(),
        max_tokens=max_completion_tokens,
    )

    title = (data.get("title") or "Community Report").strip()
    page = {
        "title": title,
        "markdown": assemble_wiki_markdown({**data, "title": title}),
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
    wiki_cfg = cfg.get("wiki_synthesizer") or {}
    max_completion_tokens = int(
        wiki_cfg.get("max_completion_tokens", DEFAULT_MAX_COMPLETION_TOKENS)
    )

    async def load_node(state: WikiState) -> dict:
        return await load_context(state)

    async def synthesize_node(state: WikiState) -> dict:
        return await synthesize_page(
            state,
            llm,
            max_completion_tokens=max_completion_tokens,
        )

    builder = StateGraph(WikiState)
    builder.add_node("load", load_node)
    builder.add_node("synthesize", synthesize_node)
    builder.add_edge(START, "load")
    builder.add_edge("load", "synthesize")
    builder.add_edge("synthesize", END)
    return builder.compile()
