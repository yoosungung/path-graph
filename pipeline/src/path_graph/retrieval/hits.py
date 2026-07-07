"""Helpers to normalize retrieval rows into SearchHit dicts."""

from __future__ import annotations

from typing import Any


def _snippet(text: str, *, max_chars: int = 400) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def chunk_row_to_hit(row: dict[str, Any]) -> dict[str, Any]:
    chunk_id = str(row.get("chunk_id") or row.get("id") or "")
    return {
        "kind": "chunk",
        "id": chunk_id,
        "text": str(row.get("text") or row.get("content") or ""),
        "score": float(row.get("vector_score") or row.get("fts_score") or row.get("score") or 0.0),
        "rrf_score": row.get("rrf_score"),
        "provenance": {
            "document_id": str(row.get("document_id") or ""),
            "chunk_id": chunk_id,
            "entity_ids": list(row.get("entity_ids") or []),
        },
    }


def wiki_row_to_hit(
    row: dict[str, Any],
    *,
    stale: bool = False,
    graph_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    community_id = str(row.get("community_id") or row.get("slug") or "")
    body = str(row.get("body_text") or "")
    title = str(row.get("title") or "")
    text = _snippet(body or title)
    provenance: dict[str, Any] = {
        "community_id": community_id,
        "slug": str(row.get("slug") or ""),
        "vfs_path": str(row.get("vfs_path") or ""),
        "batch_id": str(row.get("batch_id") or ""),
        "title": title,
    }
    if stale:
        provenance["stale"] = True
    if graph_context is not None:
        provenance["graph_context"] = graph_context
    return {
        "kind": "wiki",
        "id": community_id or str(row.get("slug") or ""),
        "text": text,
        "score": float(row.get("vector_score") or row.get("fts_score") or row.get("score") or 0.0),
        "rrf_score": row.get("rrf_score"),
        "provenance": provenance,
    }


def entity_row_to_hit(row: dict[str, Any]) -> dict[str, Any]:
    eid = str(row.get("entity_id") or row.get("id") or "")
    name = str(row.get("name") or "")
    desc = str(row.get("description") or "")
    text = f"{name} | {desc}".strip(" |")
    return {
        "kind": "entity",
        "id": eid,
        "text": text,
        "score": float(row.get("vector_score") or row.get("fts_score") or row.get("score") or 0.0),
        "rrf_score": row.get("rrf_score"),
        "provenance": {"name": name, "entity_id": eid},
    }


def relationship_row_to_hit(row: dict[str, Any]) -> dict[str, Any]:
    src = str(row.get("source") or "")
    tgt = str(row.get("target") or "")
    etype = str(row.get("type") or "EXTRACTED")
    desc = str(row.get("description") or "")
    text = f"{src} -[{etype}]-> {tgt}"
    if desc:
        text = f"{text} ({desc})"
    return {
        "kind": "relationship",
        "id": f"{src}->{tgt}",
        "text": text,
        "score": float(row.get("score") or 0.0),
        "rrf_score": row.get("rrf_score"),
        "provenance": {
            "source": src,
            "target": tgt,
            "type": etype,
            "description": desc,
        },
    }
