from __future__ import annotations

from typing import Any

from graph_extractor.graph import build_graph


def factory(cfg: dict, secrets) -> Any:
    """Return a compiled LangGraph for graph extraction."""
    return build_graph(cfg, secrets)
