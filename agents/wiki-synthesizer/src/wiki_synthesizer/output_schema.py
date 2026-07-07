"""wiki_v1 structured output schema for SGLang / OpenAI-compatible APIs."""

from __future__ import annotations

WIKI_TITLE_MAX_CHARS = 200
WIKI_SUMMARY_MAX_CHARS = 1200
WIKI_BULLET_MAX_CHARS = 300
WIKI_MAX_ENTITY_BULLETS = 8
WIKI_MAX_RELATIONSHIP_BULLETS = 8
WIKI_MAX_OPEN_QUESTIONS = 5

WIKI_V1_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": WIKI_TITLE_MAX_CHARS},
        "executive_summary": {
            "type": "string",
            "maxLength": WIKI_SUMMARY_MAX_CHARS,
        },
        "key_entities": {
            "type": "array",
            "maxItems": WIKI_MAX_ENTITY_BULLETS,
            "items": {"type": "string", "maxLength": WIKI_BULLET_MAX_CHARS},
        },
        "notable_relationships": {
            "type": "array",
            "maxItems": WIKI_MAX_RELATIONSHIP_BULLETS,
            "items": {"type": "string", "maxLength": WIKI_BULLET_MAX_CHARS},
        },
        "open_questions": {
            "type": "array",
            "maxItems": WIKI_MAX_OPEN_QUESTIONS,
            "items": {"type": "string", "maxLength": WIKI_BULLET_MAX_CHARS},
        },
    },
    "required": ["title", "executive_summary", "key_entities"],
    "additionalProperties": False,
}


def assemble_wiki_markdown(data: dict) -> str:
    title = (data.get("title") or "Community Report").strip()
    parts = [f"# {title}", ""]
    summary = (data.get("executive_summary") or "").strip()
    if summary:
        parts.extend(["## Executive Summary", summary, ""])
    entities = [str(item).strip() for item in data.get("key_entities") or [] if str(item).strip()]
    if entities:
        parts.append("## Key Entities")
        parts.extend(f"- {item}" for item in entities)
        parts.append("")
    relationships = [
        str(item).strip()
        for item in data.get("notable_relationships") or []
        if str(item).strip()
    ]
    if relationships:
        parts.append("## Notable Relationships")
        parts.extend(f"- {item}" for item in relationships)
        parts.append("")
    questions = [
        str(item).strip() for item in data.get("open_questions") or [] if str(item).strip()
    ]
    if questions:
        parts.append("## Open Questions")
        parts.extend(f"- {item}" for item in questions)
        parts.append("")
    return "\n".join(parts).strip()


def wiki_v1_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "wiki_v1",
            "schema": WIKI_V1_SCHEMA,
        },
    }
