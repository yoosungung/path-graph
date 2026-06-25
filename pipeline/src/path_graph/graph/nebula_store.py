from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._pool = None
        self._memory = memory

    def _mem(self, space: str) -> _MemorySpace:
        if self._memory is None:
            raise RuntimeError("memory backend not enabled")
        return self._memory.setdefault(space, _MemorySpace())

    def _session(self):
        from nebula3.gclient.net import ConnectionPool
        from nebula3.Config import Config

        if self._pool is None:
            cfg = Config()
            self._pool = ConnectionPool()
            ok = self._pool.init([(self._host, self._port)], cfg)
            if not ok:
                raise RuntimeError("nebula connection pool init failed")
        return self._pool.get_session(self._user, self._password)

    def ensure_space(self, space: str) -> None:
        if self._memory is not None:
            self._mem(space)
            return
        sess = self._session()
        try:
            sess.execute(f"CREATE SPACE IF NOT EXISTS {space}(vid_type=FIXED_STRING(64));")
            sess.execute(f"USE {space};")
        finally:
            sess.release()

    def upsert_entities(self, space: str, entities: list[dict[str, Any]]) -> None:
        if self._memory is not None:
            mem = self._mem(space)
            for ent in entities:
                eid = ent.get("id") or f"entity:{ent['name']}"
                mem.entities[eid] = ent
            return
        sess = self._session()
        try:
            sess.execute(f"USE {space};")
            for ent in entities:
                eid = ent.get("id") or f"entity:{ent['name']}"
                name = ent.get("name", "")
                desc = ent.get("description", "")
                sess.execute(
                    f'INSERT VERTEX IF NOT EXISTS Entity(name, description) '
                    f'VALUES "{eid}":("{name}", "{desc}");'
                )
        finally:
            sess.release()

    def upsert_edges(self, space: str, edges: list[dict[str, Any]]) -> None:
        if self._memory is not None:
            mem = self._mem(space)
            mem.edges.extend(edges)
            return
        sess = self._session()
        try:
            sess.execute(f"USE {space};")
            for edge in edges:
                etype = edge.get("type", "EXTRACTED")
                src = edge["source"]
                tgt = edge["target"]
                conf = edge.get("confidence", 1.0)
                sess.execute(
                    f'INSERT EDGE IF NOT EXISTS {etype} (confidence) '
                    f'VALUES "{src}"->"{tgt}":({conf});'
                )
        finally:
            sess.release()

    def upsert_mentions(self, space: str, chunk_id: str, entities: list[str]) -> None:
        if self._memory is not None:
            mem = self._mem(space)
            for ent in entities:
                eid = f"entity:{ent}"
                mem.entities.setdefault(eid, {"id": eid, "name": ent})
                mem.mentions.append((chunk_id, eid))
            return
        sess = self._session()
        try:
            sess.execute(f"USE {space};")
            for ent in entities:
                eid = f"entity:{ent}"
                sess.execute(
                    f'INSERT VERTEX IF NOT EXISTS Entity(name) VALUES "{eid}":("{ent}");'
                )
                sess.execute(
                    f'INSERT EDGE IF NOT EXISTS MENTIONS () VALUES "{chunk_id}"->"{eid}":();'
                )
        finally:
            sess.release()

    def export_project_graph(
        self,
        space: str,
        *,
        batch_chunk_ids: set[str] | None = None,
    ) -> list[tuple[str, str, float]]:
        """Export entity-entity edges within a single Nebula space."""
        if self._memory is not None:
            return self._export_from_memory(space, batch_chunk_ids)
        # Live Nebula: query EXTRACTED/INFERRED edges in space
        sess = self._session()
        try:
            sess.execute(f"USE {space};")
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
            if batch_chunk_ids:
                scoped = self._entity_ids_for_chunks(space, batch_chunk_ids)
                edges = [(s, t, w) for s, t, w in edges if s in scoped and t in scoped]
            return edges
        finally:
            sess.release()

    def _export_from_memory(
        self,
        space: str,
        batch_chunk_ids: set[str] | None,
    ) -> list[tuple[str, str, float]]:
        mem = self._memory.get(space) if self._memory else None
        if mem is None:
            return []
        scoped: set[str] | None = None
        if batch_chunk_ids:
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
        if not edges and scoped:
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
        return set()

    def get_entities(self, space: str, entity_ids: list[str]) -> list[dict[str, Any]]:
        if self._memory is not None:
            mem = self._memory.get(space, _MemorySpace())
            return [mem.entities[eid] for eid in entity_ids if eid in mem.entities]
        return [{"id": eid, "name": eid.removeprefix("entity:")} for eid in entity_ids]

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
            for cid in chunk_ids:
                mem.entities.pop(f"chunk:{cid}", None)
                mem.entities.pop(cid, None)
            return len(chunk_ids)
        sess = self._session()
        deleted = 0
        try:
            sess.execute(f"USE {space};")
            for cid in chunk_ids:
                sess.execute(f'DELETE VERTEX "{cid}";')
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
            sess.execute(f"DROP SPACE IF EXISTS {space};")
            return True
        finally:
            sess.release()

    def list_chunk_vertices(self, space: str) -> list[str]:
        if self._memory is not None:
            mem = self._memory.get(space, _MemorySpace())
            return sorted({cid for cid, _ in mem.mentions})
        return []


def _decode_value(val: Any) -> str:
    if val is None:
        return ""
    if hasattr(val, "get_sVal"):
        raw = val.get_sVal()
        return raw.decode() if isinstance(raw, bytes) else str(raw)
    return str(val)
