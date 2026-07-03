from __future__ import annotations

import re
import uuid
from typing import Any

from path_graph.ids import PATH_GRAPH_NAMESPACE

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def entity_vid(name: str) -> str:
    """Canonical Nebula Entity VID (uuid5, always <= 36 UTF-8 bytes)."""
    normalized = str(name).strip()
    if not normalized:
        raise ValueError("entity name required")
    return str(uuid.uuid5(PATH_GRAPH_NAMESPACE, f"entity:{normalized}"))


def resolve_entity_vid(ref: str) -> str:
    """Map graph-extractor / wikilink ref to canonical Entity VID."""
    value = str(ref).strip()
    if not value:
        raise ValueError("empty entity ref")
    if _UUID_RE.match(value):
        return value
    if value.startswith("entity:"):
        return entity_vid(value.removeprefix("entity:"))
    return entity_vid(value)


def normalize_entity_record(ent: dict[str, Any]) -> dict[str, Any]:
    name = str(ent.get("name") or "").strip()
    if not name:
        raw_id = str(ent.get("id") or "").strip()
        name = raw_id.removeprefix("entity:").strip()
    if not name:
        raise ValueError("entity record requires name or id")
    return {
        "id": entity_vid(name),
        "name": name,
        "description": str(ent.get("description") or ""),
    }


def normalize_semantic_graph(semantic: dict[str, Any]) -> dict[str, Any]:
    entities = [
        normalize_entity_record(ent)
        for ent in (semantic.get("entities") or [])
        if ent.get("name") or ent.get("id")
    ]
    edges: list[dict[str, Any]] = []
    for edge in semantic.get("edges") or []:
        src = edge.get("source")
        tgt = edge.get("target")
        if not src or not tgt:
            continue
        edges.append(
            {
                "type": edge.get("type", "EXTRACTED"),
                "source": resolve_entity_vid(str(src)),
                "target": resolve_entity_vid(str(tgt)),
                "confidence": edge.get("confidence", 1.0),
                "description": edge.get("description", ""),
            }
        )
    return {"entities": entities, "edges": edges}
