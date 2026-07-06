from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from path_graph.graph.nebula_store import (
    NebulaGraphStore,
    _decode_value,
    _ngql_string,
    _schema_edge_types,
    _schema_tag_names,
)


class _FakeValue:
    def __init__(self, text: str) -> None:
        self._text = text

    def get_sVal(self) -> bytes:
        return self._text.encode()


class _FakeRow:
    def __init__(self, text: str) -> None:
        self.values = [_FakeValue(text)]


class _FakeResult:
    def __init__(
        self,
        *,
        ok: bool = True,
        rows: list[_FakeRow] | None = None,
        error: str = "",
    ) -> None:
        self._ok = ok
        self._rows = rows or []
        self._error = error

    def is_succeeded(self) -> bool:
        return self._ok

    def error_msg(self) -> str:
        return self._error

    def rows(self) -> list[_FakeRow]:
        return self._rows


def test_ngql_string_escapes_quotes() -> None:
    assert _ngql_string('a"b') == '"a\\"b"'


def test_schema_name_helpers() -> None:
    assert "Entity" in _schema_tag_names()
    assert "Chunk" in _schema_tag_names()
    assert {"EXTRACTED", "INFERRED", "MENTIONS"} <= _schema_edge_types()


def test_ensure_space_live_applies_schema_ddl() -> None:
    store = NebulaGraphStore(
        "h",
        9669,
        "root",
        "pw",
        schema_wait_sec=0.1,
        schema_poll_interval_sec=0.01,
    )
    session = MagicMock()
    tags_seen = {"count": 0}
    use_attempts = {"count": 0}

    def execute(nql: str) -> _FakeResult:
        if nql.strip().startswith("USE path_graph_dev_test"):
            use_attempts["count"] += 1
            if use_attempts["count"] < 2:
                return _FakeResult(
                    ok=False,
                    error="SpaceNotFound: SpaceName `path_graph_dev_test`",
                )
            return _FakeResult()
        if nql.strip() == "SHOW TAGS;":
            tags_seen["count"] += 1
            if tags_seen["count"] >= 2:
                return _FakeResult(rows=[_FakeRow("Entity"), _FakeRow("Chunk")])
            return _FakeResult(rows=[])
        if nql.strip() == "SHOW EDGES;":
            return _FakeResult(
                rows=[
                    _FakeRow("EXTRACTED"),
                    _FakeRow("INFERRED"),
                    _FakeRow("MENTIONS"),
                ]
            )
        return _FakeResult()

    session.execute.side_effect = execute

    with patch.object(store, "_session", return_value=session):
        store.ensure_space("path_graph_dev_test")

    assert use_attempts["count"] >= 2
    joined = "\n".join(call.args[0] for call in session.execute.call_args_list)
    assert "CREATE SPACE IF NOT EXISTS path_graph_dev_test" in joined
    assert "SHOW SPACES" not in joined
    assert "CREATE TAG IF NOT EXISTS Entity" in joined
    assert "CREATE TAG IF NOT EXISTS Chunk" in joined
    assert "CREATE EDGE IF NOT EXISTS EXTRACTED" in joined
    assert "CREATE EDGE IF NOT EXISTS INFERRED" in joined
    assert "CREATE EDGE IF NOT EXISTS MENTIONS" in joined


def test_upsert_entities_raises_on_nebula_error() -> None:
    store = NebulaGraphStore("h", 9669, "root", "pw")
    session = MagicMock()
    session.execute.return_value = _FakeResult(ok=False, error="No schema found for Entity")

    with patch.object(store, "_session", return_value=session):
        with pytest.raises(RuntimeError, match="No schema found"):
            store.upsert_entities(
                "space",
                [{"id": "entity:A", "name": "A", "description": ""}],
            )


def test_upsert_mentions_live_creates_chunk_vertex() -> None:
    store = NebulaGraphStore("h", 9669, "root", "pw")
    session = MagicMock()
    session.execute.return_value = _FakeResult()

    with (
        patch.object(store, "_ensure_live_schema"),
        patch.object(store, "_session", return_value=session),
    ):
        store.upsert_mentions("space", "chunk-1", ["Alpha"])

    joined = "\n".join(call.args[0] for call in session.execute.call_args_list)
    assert "INSERT VERTEX IF NOT EXISTS Chunk()" in joined
    assert 'VALUES "chunk-1":()' in joined
    assert "INSERT EDGE IF NOT EXISTS MENTIONS" in joined


def test_entity_ids_for_chunks_live_queries_mentions() -> None:
    store = NebulaGraphStore("h", 9669, "root", "pw")
    session = MagicMock()
    session.execute.return_value = _FakeResult(
        rows=[_FakeRow("entity:Alpha"), _FakeRow("entity:Beta")]
    )

    with patch.object(store, "_session", return_value=session):
        ids = store._entity_ids_for_chunks("space", {"chunk-1", "chunk-2"})

    assert ids == {"entity:Alpha", "entity:Beta"}
    nql = session.execute.call_args_list[-1].args[0]
    assert "MENTIONS" in nql
    assert "chunk-1" in nql
    assert "chunk-2" in nql


def test_delete_chunks_skips_missing_space() -> None:
    store = NebulaGraphStore("h", 9669, "root", "pw")
    session = MagicMock()
    session.execute.return_value = _FakeResult(rows=[])

    with patch.object(store, "_session", return_value=session):
        deleted = store.delete_chunks("path_graph_dev_missing", ["chunk-1"])

    assert deleted == 0
    joined = "\n".join(call.args[0] for call in session.execute.call_args_list)
    assert "USE path_graph_dev_missing" not in joined


def test_decode_value_bytes() -> None:
    assert _decode_value(_FakeValue("entity:x")) == "entity:x"
