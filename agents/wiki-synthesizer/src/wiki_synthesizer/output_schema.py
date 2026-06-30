"""wiki_v1 structured output schema for SGLang / OpenAI-compatible APIs."""

from __future__ import annotations

WIKI_V1_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "slug": {"type": "string"},
        "title": {"type": "string"},
        "markdown": {"type": "string"},
    },
    "required": ["slug", "title", "markdown"],
    "additionalProperties": False,
}


def wiki_v1_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "wiki_v1",
            "schema": WIKI_V1_SCHEMA,
        },
    }
