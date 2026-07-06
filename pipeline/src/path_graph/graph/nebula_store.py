from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from path_graph.graph.entity_vid import (
    entity_vid,
    normalize_entity_record,
    resolve_entity_vid,
)


@dataclass
class HierarchicalCluster:
    level: int
    cluster_key: str
    entity_ids: list[str]
    parent_cluster_key: str | None = None


@dataclass
class _MemorySpace:
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    mentions: list[tuple[str, str]] = field(default_factory=list)
    chunks: set[str] = field(default_factory=set)


_SCHEMA_TAG_DDL = (
    "CREATE TAG IF NOT EXISTS Entity(name string, description string);",
    "CREATE TAG IF NOT EXISTS Chunk();",
)
_SCHEMA_EDGE_DDL = (
    "CREATE EDGE IF NOT EXISTS EXTRACTED(confidence double);",
    "CREATE EDGE IF NOT EXISTS INFERRED(confidence double);",
    "CREATE EDGE IF NOT EXISTS MENTIONS();",
)


def _schema_tag_names() -> set[str]:
    return {"Entity", "Chunk"}


def _schema_edge_types() -> set[str]:
    return {"EXTRACTED", "INFERRED", "MENTIONS"}


def _ngql_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class NebulaGraphStore:
    """Nebula wrapper with optional in-memory backend for unit tests."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        *,
        memory: dict[str, _MemorySpace] | None = None,
        schema_wait_sec: float = 20.0,
        schema_poll_interval_sec: float = 1.0,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._pool = None
        self._memory = memory
        self._schema_wait_sec = schema_wait_sec
        self._schema_poll_interval_sec = schema_poll_interval_sec
        self._prepared_spaces: set[str] = set()

    def _mem(self, space: str) -> _MemorySpace:
        if self._memory is None:
            raise RuntimeError("memory backend not enabled")
        return self._memory.setdefault(space, _MemorySpace())

    def _session(self):
        from nebula3.Config import Config
        from nebula3.gclient.net import ConnectionPool

        if self._pool is None:
            cfg = Config()
            self._pool = ConnectionPool()
            ok = self._pool.init([(self._host, self._port)], cfg)
            if not ok:
                raise RuntimeError("nebula connection pool init failed")
        return self._pool.get_session(self._user, self._password)

    def _execute(self, sess: Any, nql: str) -> Any:
        result = sess.execute(nql)
        if not result.is_succeeded():
            raise RuntimeError(result.error_msg() or f"nebula query failed: {nql}")
        return result

    def _wait_until(self, sess: Any, *, ready: Any, label: str) -> None:
        deadline = time.monotonic() + self._schema_wait_sec
        while time.monotonic() < deadline:
            if ready(sess):
                return
            time.sleep(self._schema_poll_interval_sec)
        raise RuntimeError(f"nebula {label} not ready within {self._schema_wait_sec}s")

    def _space_visible(self, sess: Any, space: str) -> bool:
        result = sess.execute("SHOW SPACES;")
        if not result.is_succeeded():
            return False
        for row in result.rows():
            if _decode_value(row.values[0]) == space:
                return True
        return False

    def _space_usable(self, sess: Any, space: str) -> bool:
        """True when graphd session cache accepts USE (not just SHOW SPACES)."""
        result = sess.execute(f"USE {space};")
        return result.is_succeeded()

    def _schema_ready(self, sess: Any) -> bool:
        tags = sess.execute("SHOW TAGS;")
        if not tags.is_succeeded():
            return False
        tag_names = {_decode_value(row.values[0]) for row in tags.rows()}
        if not _schema_tag_names() <= tag_names:
            return False
        edges = sess.execute("SHOW EDGES;")
        if not edges.is_succeeded():
            return False
        edge_names = {_decode_value(row.values[0]) for row in edges.rows()}
        return _schema_edge_types() <= edge_names

    def _ensure_live_schema(self, sess: Any, space: str) -> None:
        if space in self._prepared_spaces:
            return
        self._execute(sess, f"CREATE SPACE IF NOT EXISTS {space}(vid_type=FIXED_STRING(64));")
        self._wait_until(
            sess,
            ready=lambda s: self._space_usable(s, space),
            label=f"space {space}",
        )
        for ddl in (*_SCHEMA_TAG_DDL, *_SCHEMA_EDGE_DDL):
            self._execute(sess, ddl)
        self._wait_until(sess, ready=self._schema_ready, label=f"schema in {space}")
        self._prepared_spaces.add(space)

    def ensure_space(self, space: str) -> None:
        if self._memory is not None:
            self._mem(space)
            return
        sess = self._session()
        try:
            self._ensure_live_schema(sess, space)
        finally:
            sess.release()

    def upsert_entities(self, space: str, entities: list[dict[str, Any]]) -> None:
        if self._memory is not None:
            mem = self._mem(space)
            for ent in entities:
                norm = normalize_entity_record(ent)
                mem.entities[norm["id"]] = norm
            return
        if not entities:
            return
        sess = self._session()
        try:
            self._ensure_live_schema(sess, space)
            self._execute(sess, f"USE {space};")
            for ent in entities:
                norm = normalize_entity_record(ent)
                eid = norm["id"]
                name = norm["name"]
                desc = norm["description"]
                self._execute(
                    sess,
                    "INSERT VERTEX IF NOT EXISTS Entity(name, description) "
                    f"VALUES {_ngql_string(eid)}:({_ngql_string(name)}, {_ngql_string(desc)});",
                )
        finally:
            sess.release()

    def upsert_edges(self, space: str, edges: list[dict[str, Any]]) -> None:
        if self._memory is not None:
            mem = self._mem(space)
            for edge in edges:
                mem.edges.append(
                    {
                        **edge,
                        "source": resolve_entity_vid(str(edge["source"])),
                        "target": resolve_entity_vid(str(edge["target"])),
                    }
                )
            return
        if not edges:
            return
        sess = self._session()
        try:
            self._ensure_live_schema(sess, space)
            self._execute(sess, f"USE {space};")
            for edge in edges:
                etype = edge.get("type", "EXTRACTED")
                src = resolve_entity_vid(str(edge["source"]))
                tgt = resolve_entity_vid(str(edge["target"]))
                conf = edge.get("confidence", 1.0)
                self._execute(
                    sess,
                    f"INSERT EDGE IF NOT EXISTS {etype} (confidence) "
                    f"VALUES {_ngql_string(src)}->{_ngql_string(tgt)}:({conf});",
                )
        finally:
            sess.release()

    def upsert_mentions(self, space: str, chunk_id: str, entities: list[str]) -> None:
        if self._memory is not None:
            mem = self._mem(space)
            mem.chunks.add(chunk_id)
            for ent in entities:
                eid = entity_vid(ent)
                mem.entities.setdefault(eid, {"id": eid, "name": ent})
                mem.mentions.append((chunk_id, eid))
            return
        if not entities:
            return
        sess = self._session()
        try:
            self._ensure_live_schema(sess, space)
            self._execute(sess, f"USE {space};")
            self._execute(
                sess,
                f"INSERT VERTEX IF NOT EXISTS Chunk() VALUES {_ngql_string(chunk_id)}:();",
            )
            for ent in entities:
                eid = entity_vid(ent)
                self._execute(
                    sess,
                    "INSERT VERTEX IF NOT EXISTS Entity(name) "
                    f"VALUES {_ngql_string(eid)}:({_ngql_string(ent)});",
                )
                self._execute(
                    sess,
                    "INSERT EDGE IF NOT EXISTS MENTIONS () "
                    f"VALUES {_ngql_string(chunk_id)}->{_ngql_string(eid)}:();",
                )
        finally:
            sess.release()

    def _resolve_batch_scope(
        self,
        space: str,
        *,
        batch_entity_ids: set[str] | None,
        batch_chunk_ids: set[str] | None,
    ) -> set[str] | None:
        if batch_entity_ids is not None:
            return batch_entity_ids
        if batch_chunk_ids:
            return self._entity_ids_for_chunks(space, batch_chunk_ids)
        return None

    def export_project_graph(
        self,
        space: str,
        *,
        batch_chunk_ids: set[str] | None = None,
        batch_entity_ids: set[str] | None = None,
    ) -> list[tuple[str, str, float]]:
        """Export entity-entity edges within a single Nebula space."""
        if self._memory is not None:
            return self._export_from_memory(
                space, batch_chunk_ids, batch_entity_ids=batch_entity_ids
            )
        sess = self._session()
        try:
            self._execute(sess, f"USE {space};")
            result = sess.execute(
                "MATCH (a:Entity)-[e:EXTRACTED|INFERRED]->(b:Entity) "
                "RETURN id(a) AS src, id(b) AS tgt, type(e) AS etype;"
            )
            if not result.is_succeeded():
                return []
            edges: list[tuple[str, str, float]] = []
            for row in result.rows():
                src = _decode_value(row.values[0])
                tgt = _decode_value(row.values[1])
                if src and tgt:
                    edges.append((src, tgt, 1.0))
            scoped = self._resolve_batch_scope(
                space,
                batch_entity_ids=batch_entity_ids,
                batch_chunk_ids=batch_chunk_ids,
            )
            if scoped is not None:
                edges = [(s, t, w) for s, t, w in edges if s in scoped and t in scoped]
            return edges
        finally:
            sess.release()

    def _export_from_memory(
        self,
        space: str,
        batch_chunk_ids: set[str] | None,
        *,
        batch_entity_ids: set[str] | None = None,
    ) -> list[tuple[str, str, float]]:
        mem = self._memory.get(space) if self._memory else None
        if mem is None:
            return []
        scoped: set[str] | None = None
        if batch_entity_ids is not None:
            scoped = batch_entity_ids
        elif batch_chunk_ids:
            scoped = {
                eid
                for chunk_id, eid in mem.mentions
                if chunk_id in batch_chunk_ids
            }
        edges: list[tuple[str, str, float]] = []
        for edge in mem.edges:
            etype = edge.get("type", "EXTRACTED")
            if etype not in ("EXTRACTED", "INFERRED"):
                continue
            src = edge["source"]
            tgt = edge["target"]
            if scoped is not None and (src not in scoped or tgt not in scoped):
                continue
            weight = float(edge.get("confidence", 1.0))
            edges.append((src, tgt, weight))
        if not edges and scoped and batch_entity_ids is None:
            # Wikilink-only graphs: infer co-mention edges between entities in batch
            entity_list = sorted(scoped)
            for i, a in enumerate(entity_list):
                for b in entity_list[i + 1 :]:
                    edges.append((a, b, 0.5))
        return edges

    def _entity_ids_for_chunks(self, space: str, chunk_ids: set[str]) -> set[str]:
        if self._memory is not None:
            mem = self._memory.get(space, _MemorySpace())
            return {eid for cid, eid in mem.mentions if cid in chunk_ids}
        if not chunk_ids:
            return set()
        sess = self._session()
        try:
            self._execute(sess, f"USE {space};")
            ids_literal = ", ".join(_ngql_string(cid) for cid in sorted(chunk_ids))
            result = sess.execute(
                "MATCH (c)-[:MENTIONS]->(e:Entity) "
                f"WHERE id(c) IN [{ids_literal}] "
                "RETURN DISTINCT id(e) AS eid;"
            )
            if not result.is_succeeded():
                return set()
            return {_decode_value(row.values[0]) for row in result.rows() if row.values}
        finally:
            sess.release()

    def get_entities(self, space: str, entity_ids: list[str]) -> list[dict[str, Any]]:
        if self._memory is not None:
            mem = self._memory.get(space, _MemorySpace())
            return [mem.entities[eid] for eid in entity_ids if eid in mem.entities]
        if not entity_ids:
            return []
        sess = self._session()
        try:
            self._execute(sess, f"USE {space};")
            ids_literal = ", ".join(_ngql_string(eid) for eid in entity_ids)
            result = sess.execute(
                "MATCH (v:Entity) "
                f"WHERE id(v) IN [{ids_literal}] "
                "RETURN id(v) AS id, v.Entity.name AS name, v.Entity.description AS description;"
            )
            if not result.is_succeeded():
                return [
                    {"id": eid, "name": "", "description": ""} for eid in entity_ids
                ]
            by_id: dict[str, dict[str, Any]] = {}
            for row in result.rows():
                values = row.values
                eid = _decode_value(values[0])
                by_id[eid] = {
                    "id": eid,
                    "name": _decode_value(values[1]) if len(values) > 1 else "",
                    "description": _decode_value(values[2]) if len(values) > 2 else "",
                }
            return [by_id.get(eid, {"id": eid, "name": "", "description": ""}) for eid in entity_ids]
        finally:
            sess.release()

    def get_relationships(
        self, space: str, entity_ids: set[str]
    ) -> list[dict[str, Any]]:
        if self._memory is not None:
            mem = self._memory.get(space, _MemorySpace())
            rels: list[dict[str, Any]] = []
            for edge in mem.edges:
                src = edge["source"]
                tgt = edge["target"]
                if src in entity_ids and tgt in entity_ids:
                    rels.append(edge)
            return rels
        return []

    def delete_chunks(self, space: str, chunk_ids: list[str]) -> int:
        if not chunk_ids:
            return 0
        if self._memory is not None:
            mem = self._mem(space)
            chunk_set = set(chunk_ids)
            mem.mentions = [
                (cid, eid) for cid, eid in mem.mentions if cid not in chunk_set
            ]
            mem.chunks -= chunk_set
            for cid in chunk_ids:
                mem.entities.pop(f"chunk:{cid}", None)
                mem.entities.pop(cid, None)
            return len(chunk_ids)
        sess = self._session()
        deleted = 0
        try:
            if not self._space_visible(sess, space):
                return 0
            self._execute(sess, f"USE {space};")
            for cid in chunk_ids:
                self._execute(sess, f"DELETE VERTEX {_ngql_string(cid)};")
                deleted += 1
        finally:
            sess.release()
        return deleted

    def prune_orphan_entities(self, space: str) -> int:
        if self._memory is not None:
            mem = self._mem(space)
            referenced = {eid for _, eid in mem.mentions}
            for edge in mem.edges:
                referenced.add(edge["source"])
                referenced.add(edge["target"])
            orphans = [eid for eid in list(mem.entities) if eid not in referenced]
            for eid in orphans:
                mem.entities.pop(eid, None)
            return len(orphans)
        return 0

    def drop_space(self, space: str) -> bool:
        if self._memory is not None:
            if space in self._memory:
                del self._memory[space]
                return True
            return False
        sess = self._session()
        try:
            self._execute(sess, f"DROP SPACE IF EXISTS {space};")
            self._prepared_spaces.discard(space)
            return True
        finally:
            sess.release()

    def list_chunk_vertices(self, space: str) -> list[str]:
        if self._memory is not None:
            mem = self._memory.get(space, _MemorySpace())
            return sorted(mem.chunks or {cid for cid, _ in mem.mentions})
        return []


def _decode_value(val: Any) -> str:
    if val is None:
        return ""
    if hasattr(val, "get_sVal"):
        raw = val.get_sVal()
        return raw.decode() if isinstance(raw, bytes) else str(raw)
    return str(val)
