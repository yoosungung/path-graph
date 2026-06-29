from __future__ import annotations

from typing import Any

from wiki_synthesizer.graph import build_graph


def factory(cfg: dict, secrets) -> Any:
    """Return a compiled LangGraph for wiki synthesis."""
    return build_graph(cfg, secrets)
