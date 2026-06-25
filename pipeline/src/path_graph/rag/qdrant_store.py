from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from path_graph.config import Settings, get_settings
from path_graph.ids import qdrant_collection_name


class QdrantStore:
    def __init__(self, client, settings: Settings | None = None) -> None:
        self._client = client
        self._settings = settings or get_settings()

    def collection_for_project(self, tenant: str, project_slug: str) -> str:
        return qdrant_collection_name(tenant, project_slug)

    def ensure_collection(self, tenant: str, project_slug: str) -> None:
        from qdrant_client.models import Distance, VectorParams

        name = qdrant_collection_name(tenant, project_slug)
        dim = self._settings.embedding_dim
        if not self._client.collection_exists(name):
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert_chunks(
        self,
        tenant: str,
        project_slug: str,
        chunk_ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        payloads: Sequence[dict],
    ) -> None:
        from qdrant_client.models import PointStruct

        self.ensure_collection(tenant, project_slug)
        name = qdrant_collection_name(tenant, project_slug)
        points = [
            PointStruct(id=cid, vector=list(vec), payload=payload)
            for cid, vec, payload in zip(chunk_ids, vectors, payloads, strict=True)
        ]
        self._client.upsert(collection_name=name, points=points)

    def delete_by_document_id(
        self,
        tenant: str,
        project_slug: str,
        document_id: str,
        *,
        project_id: str | None = None,
    ) -> int:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        name = qdrant_collection_name(tenant, project_slug)
        if not self._client.collection_exists(name):
            return 0
        must = [FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        if project_id:
            must.append(
                FieldCondition(key="project_id", match=MatchValue(value=project_id))
            )
        result = self._client.delete(
            collection_name=name,
            points_selector=Filter(must=must),
        )
        return int(getattr(result, "operation_id", 0) or 1)

    def delete_by_chunk_ids(
        self,
        tenant: str,
        project_slug: str,
        chunk_ids: list[str],
    ) -> int:
        if not chunk_ids:
            return 0
        name = qdrant_collection_name(tenant, project_slug)
        if not self._client.collection_exists(name):
            return 0
        self._client.delete(collection_name=name, points_selector=chunk_ids)
        return len(chunk_ids)

    def scroll_chunk_ids(
        self,
        tenant: str,
        project_slug: str,
        *,
        project_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return (chunk_id, document_id) for all points in collection."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        name = qdrant_collection_name(tenant, project_slug)
        if not self._client.collection_exists(name):
            return []
        qfilter = None
        if project_id:
            qfilter = Filter(
                must=[
                    FieldCondition(
                        key="project_id", match=MatchValue(value=project_id)
                    )
                ]
            )
        pairs: list[tuple[str, str]] = []
        offset = None
        while True:
            records, offset = self._client.scroll(
                collection_name=name,
                scroll_filter=qfilter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in records:
                payload = point.payload or {}
                cid = str(payload.get("chunk_id") or point.id)
                did = str(payload.get("document_id") or "")
                pairs.append((cid, did))
            if offset is None:
                break
        return pairs

    def delete_collection(self, collection_name: str) -> bool:
        if self._client.collection_exists(collection_name):
            self._client.delete_collection(collection_name)
            return True
        return False

    def optimize_collection(self, tenant: str, project_slug: str) -> None:
        name = qdrant_collection_name(tenant, project_slug)
        if self._client.collection_exists(name):
            self._client.update_collection(
                collection_name=name,
                optimizer_config={"indexing_threshold": 10000},
            )


def make_qdrant_store(settings: Settings | None = None) -> QdrantStore:
    from qdrant_client import QdrantClient

    s = settings or get_settings()
    client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
    return QdrantStore(client, s)
