"""Entity Nebula VID: uuid5 from name, UTF-8 byte limit safe."""

from __future__ import annotations

import re

import pytest

from path_graph.graph.entity_vid import (
    entity_vid,
    normalize_entity_record,
    normalize_semantic_graph,
    resolve_entity_vid,
)

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

LONG_KOREAN = "제31조(근로시간 및 휴게, 휴일의 적용 제외)"


def test_entity_vid_is_uuid5_and_fits_nebula_fixed_string_64() -> None:
    vid = entity_vid(LONG_KOREAN)
    assert _UUID_RE.match(vid)
    assert len(vid.encode("utf-8")) <= 64
    assert len(f"entity:{LONG_KOREAN}".encode("utf-8")) > 64


def test_entity_vid_deterministic() -> None:
    assert entity_vid("Alpha") == entity_vid("Alpha")
    assert entity_vid("Alpha") != entity_vid("Beta")


def test_resolve_entity_vid_legacy_and_bare_name_match() -> None:
    assert resolve_entity_vid("entity:Alpha") == entity_vid("Alpha")
    assert resolve_entity_vid("Alpha") == entity_vid("Alpha")


def test_resolve_entity_vid_passes_through_canonical_uuid() -> None:
    canonical = entity_vid("Alpha")
    assert resolve_entity_vid(canonical) == canonical


def test_normalize_entity_record_preserves_name() -> None:
    rec = normalize_entity_record(
        {"id": "entity:프로젝트 지원 규정", "name": "프로젝트 지원 규정"}
    )
    assert rec["name"] == "프로젝트 지원 규정"
    assert rec["id"] == entity_vid("프로젝트 지원 규정")


def test_normalize_semantic_graph_rewrites_edges() -> None:
    semantic = normalize_semantic_graph(
        {
            "entities": [
                {"id": "entity:A", "name": "A"},
                {"id": "entity:B", "name": "B"},
            ],
            "edges": [
                {
                    "type": "EXTRACTED",
                    "source": "entity:A",
                    "target": "B",
                    "confidence": 0.9,
                }
            ],
        }
    )
    assert len(semantic["entities"]) == 2
    assert semantic["edges"][0]["source"] == entity_vid("A")
    assert semantic["edges"][0]["target"] == entity_vid("B")


def test_normalize_entity_record_requires_name_or_id() -> None:
    with pytest.raises(ValueError, match="name or id"):
        normalize_entity_record({})
