from __future__ import annotations

from typing import Any

from wiki_synthesizer.paths import read_prompt


def _wiki_slug(project_slug: str, level: int, community_id: str) -> str:
    short = community_id.replace("-", "")[:8]
    return f"{project_slug}-community-L{level}-{short}"


def factory(cfg: dict, secrets) -> Any:
    """Return a minimal callable agent for wiki synthesis."""

    class WikiSynthesizer:
        async def ainvoke(self, input: dict, config: dict | None = None, **kwargs) -> dict:
            project_id = input.get("project_id", "")
            community_id = input.get("community_id", "")
            level = int(input.get("community_level", 0))
            project_slug = input.get("project_slug", "project")
            _ = read_prompt("community_report.txt")
            slug = (
                _wiki_slug(project_slug, level, community_id)
                if community_id
                else f"{project_slug}-community-stub"
            )
            return {
                "pages": [],
                "tenant": input.get("tenant"),
                "project_id": project_id,
                "note": "skeleton — replace with LangGraph compiled graph",
                "expected_slug": slug,
            }

    return WikiSynthesizer()
