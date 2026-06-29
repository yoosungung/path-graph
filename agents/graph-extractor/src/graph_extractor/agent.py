from __future__ import annotations

from typing import Any

from graph_extractor.paths import read_prompt


def factory(cfg: dict, secrets) -> Any:
    """Return a minimal callable agent for graph extraction."""

    class GraphExtractor:
        async def ainvoke(self, input: dict, config: dict | None = None, **kwargs) -> dict:
            project_id = input.get("project_id", "")
            _ = read_prompt("extract_graph.txt")
            return {
                "entities": [],
                "edges": [],
                "schema": input.get("output_schema", "graph_v1"),
                "tenant": input.get("tenant"),
                "project_id": project_id,
                "note": "skeleton — replace with LangGraph compiled graph",
            }

    return GraphExtractor()
