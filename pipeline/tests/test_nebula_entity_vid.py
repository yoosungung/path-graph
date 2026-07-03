"""Nebula entity VID normalization (Korean names, get_entities)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from path_graph.graph.entity_vid import entity_vid
from path_graph.graph.nebula_store import NebulaGraphStore


def test_upsert_mentions_korean_name_uses_uuid_vid_memory() -> None:
    name = "제31조(근로시간 및 휴게, 휴일의 적용 제외)"
    memory: dict = {}
    nebula = NebulaGraphStore("h", 9669, "root", "pw", memory=memory)
    nebula.upsert_mentions("space", "chunk-1", [name])
    vid = entity_vid(name)
    assert vid in memory["space"].entities
    assert memory["space"].entities[vid]["name"] == name
    assert len(vid.encode("utf-8")) <= 64


def test_get_entities_live_fetches_name_property() -> None:
    vid = entity_vid("Alpha")
    store = NebulaGraphStore("h", 9669, "root", "pw")

    class _Row:
        def __init__(self, *cols: str) -> None:
            self.values = [_Col(c) for c in cols]

    class _Col:
        def __init__(self, text: str) -> None:
            self._text = text

        def get_sVal(self) -> bytes:
            return self._text.encode()

    class _Result:
        def is_succeeded(self) -> bool:
            return True

        def rows(self) -> list[_Row]:
            return [_Row(vid, "Alpha", "desc")]

    session = MagicMock()
    session.execute.return_value = _Result()

    with (
        patch.object(store, "_ensure_live_schema"),
        patch.object(store, "_session", return_value=session),
    ):
        entities = store.get_entities("space", [vid])

    assert entities == [{"id": vid, "name": "Alpha", "description": "desc"}]
