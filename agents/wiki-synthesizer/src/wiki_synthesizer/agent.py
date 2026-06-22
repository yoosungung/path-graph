from __future__ import annotations

from pathlib import Path
from typing import Any

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "community_report.txt"


def _wiki_slug(project: int, level: int, community_id: str) -> str:
    short = community_id.replace("-", "")[:8]
    return f"p{project}-community-L{level}-{short}"


def factory(cfg: dict, secrets) -> Any:
    """Return a minimal callable agent for wiki synthesis."""

    class WikiSynthesizer:
        async def ainvoke(self, input: dict, config: dict | None = None, **kwargs) -> dict:
            project = int(input.get("project", 0))
            community_id = input.get("community_id", "")
            level = int(input.get("community_level", 0))
            _ = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
            slug = (
                _wiki_slug(project, level, community_id)
                if community_id
                else f"p{project}-community-stub"
            )
            return {
                "pages": [],
                "tenant": input.get("tenant"),
                "project": project,
                "note": "skeleton — replace with LangGraph compiled graph",
                "expected_slug": slug,
            }

    return WikiSynthesizer()
