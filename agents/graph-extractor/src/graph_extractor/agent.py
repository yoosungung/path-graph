from __future__ import annotations

from pathlib import Path
from typing import Any


_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "extract_graph.txt"


def factory(cfg: dict, secrets) -> Any:
    """Return a minimal callable agent for graph extraction."""

    class GraphExtractor:
        async def ainvoke(self, input: dict, config: dict | None = None, **kwargs) -> dict:
            project_id = input.get("project_id", "")
            _ = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
            return {
                "entities": [],
                "edges": [],
                "schema": input.get("output_schema", "graph_v1"),
                "tenant": input.get("tenant"),
                "project_id": project_id,
                "note": "skeleton — replace with LangGraph compiled graph",
            }

    return GraphExtractor()
