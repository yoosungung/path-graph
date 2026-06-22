from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from path_graph.config import Settings, get_settings
from path_graph.ids import qdrant_collection_for_chunk, qdrant_collection_name, tenant_project_index


class QdrantStore:
    def __init__(self, client, settings: Settings | None = None) -> None:
        self._client = client
        self._settings = settings or get_settings()

    def collection_for(self, tenant: str, chunk_id: str) -> str:
        n = self._settings.path_graph_projects_per_tenant
        return qdrant_collection_for_chunk(tenant, chunk_id, n)

    def ensure_collection(self, tenant: str, project: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        name = qdrant_collection_name(tenant, project)
        dim = self._settings.embedding_dim
        if not self._client.collection_exists(name):
            self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )

    def upsert_chunks(
        self,
        tenant: str,
        chunk_ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        payloads: Sequence[dict],
    ) -> None:
        from qdrant_client.models import PointStruct

        n = self._settings.path_graph_projects_per_tenant
        by_collection: dict[str, list[PointStruct]] = defaultdict(list)
        for cid, vec, payload in zip(chunk_ids, vectors, payloads, strict=True):
            project = tenant_project_index(cid, n)
            self.ensure_collection(tenant, project)
            name = qdrant_collection_name(tenant, project)
            by_collection[name].append(PointStruct(id=cid, vector=list(vec), payload=payload))

        for name, points in by_collection.items():
            self._client.upsert(collection_name=name, points=points)


def make_qdrant_store(settings: Settings | None = None) -> QdrantStore:
    from qdrant_client import QdrantClient

    s = settings or get_settings()
    client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
    return QdrantStore(client, s)
