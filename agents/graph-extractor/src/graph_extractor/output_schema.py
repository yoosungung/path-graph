"""graph_v1 structured output schema for SGLang / OpenAI-compatible APIs."""

from __future__ import annotations

GRAPH_V1_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["id", "name"],
                "additionalProperties": False,
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["EXTRACTED", "INFERRED"]},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "confidence": {"type": "number"},
                    "description": {"type": "string"},
                },
                "required": ["type", "source", "target"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["entities", "edges"],
    "additionalProperties": False,
}


def graph_v1_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "graph_v1",
            "schema": GRAPH_V1_SCHEMA,
        },
    }
