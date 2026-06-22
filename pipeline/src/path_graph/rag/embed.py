from __future__ import annotations

from typing import Sequence

import httpx

from path_graph.config import Settings, get_settings
from path_graph.contracts.schemas import ChunkRecord


class EmbeddingClient:
    """OpenAI-compatible embeddings API client (TEI / bge-m3)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        batch_size = self._settings.embedding_batch_size
        if batch_size < 1:
            raise ValueError("embedding_batch_size must be >= 1")

        texts_list = list(texts)
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self._settings.embedding_timeout) as client:
            for start in range(0, len(texts_list), batch_size):
                chunk = texts_list[start : start + batch_size]
                vectors.extend(self._embed_batch(client, chunk))
        return vectors

    def _embed_batch(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        base = self._settings.embedding_base_url.rstrip("/")
        url = f"{base}/v1/embeddings"
        headers: dict[str, str] = {}
        if self._settings.embedding_api_key:
            headers["Authorization"] = f"Bearer {self._settings.embedding_api_key}"
        payload = {"input": texts, "model": self._settings.embedding_model}
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        rows = sorted(body["data"], key=lambda row: row.get("index", 0))
        vectors = [row["embedding"] for row in rows]
        dim = self._settings.embedding_dim
        if len(vectors) != len(texts):
            raise ValueError(f"embedding count mismatch: expected {len(texts)}, got {len(vectors)}")
        for vec in vectors:
            if len(vec) != dim:
                raise ValueError(f"embedding dim mismatch: expected {dim}, got {len(vec)}")
        return vectors


def embed_chunks(chunks: list[ChunkRecord], settings: Settings | None = None) -> list[list[float]]:
    s = settings or get_settings()
    client = EmbeddingClient(s)
    return client.embed([c.text for c in chunks])
