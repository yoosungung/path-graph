from __future__ import annotations

import json
from typing import Any

import psycopg

from path_graph.contracts.community import CommunityRecord
from path_graph.contracts.schemas import ChunkRecord


MIGRATION_SQL = """
CREATE SCHEMA IF NOT EXISTS path_graph;

CREATE TABLE IF NOT EXISTS path_graph.documents (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    source_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    s3_raw_uri TEXT,
    s3_parsed_uri TEXT,
    ingest_state TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (tenant, id)
);

CREATE TABLE IF NOT EXISTS path_graph.chunks (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    document_id UUID NOT NULL,
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    s3_uri TEXT,
    qdrant_point_id TEXT,
    PRIMARY KEY (tenant, id)
);

CREATE TABLE IF NOT EXISTS path_graph.pipeline_runs (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    workflow_name TEXT NOT NULL,
    argo_uid TEXT,
    batch_id TEXT,
    status TEXT NOT NULL,
    PRIMARY KEY (tenant, id)
);

CREATE TABLE IF NOT EXISTS path_graph.document_ingest_state (
    tenant TEXT NOT NULL,
    document_id UUID NOT NULL,
    rag_at TIMESTAMPTZ,
    graph_at TIMESTAMPTZ,
    wiki_at TIMESTAMPTZ,
    error JSONB,
    PRIMARY KEY (tenant, document_id)
);

CREATE TABLE IF NOT EXISTS path_graph.wiki_pages (
    tenant TEXT NOT NULL,
    project INT NOT NULL DEFAULT 0,
    slug TEXT NOT NULL,
    title TEXT,
    s3_uri TEXT,
    community_id UUID,
    batch_id TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (tenant, project, slug)
);

CREATE TABLE IF NOT EXISTS path_graph.communities (
    tenant TEXT NOT NULL,
    project INT NOT NULL,
    id UUID NOT NULL,
    batch_id TEXT NOT NULL,
    level INT NOT NULL,
    parent_id UUID,
    title TEXT,
    s3_uri TEXT NOT NULL,
    entity_count INT,
    PRIMARY KEY (tenant, project, id)
);

ALTER TABLE path_graph.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE path_graph.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE path_graph.communities ENABLE ROW LEVEL SECURITY;
ALTER TABLE path_graph.wiki_pages ENABLE ROW LEVEL SECURITY;
"""

SOURCES_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS path_graph.sources (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    name TEXT NOT NULL,
    driver TEXT NOT NULL,
    source_id TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT true,
    schedule_cron TEXT,
    last_batch_id TEXT,
    last_run_at TIMESTAMPTZ,
    last_run_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, id),
    UNIQUE (tenant, name)
);

ALTER TABLE path_graph.sources ENABLE ROW LEVEL SECURITY;
"""

CREDENTIALS_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS path_graph.source_credentials (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    label TEXT NOT NULL,
    driver TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    secret_keys TEXT[] NOT NULL DEFAULT '{}',
    oauth_status TEXT NOT NULL DEFAULT 'pending',
    k8s_secret_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, id)
);

ALTER TABLE path_graph.source_credentials ENABLE ROW LEVEL SECURITY;

ALTER TABLE path_graph.sources
    ADD COLUMN IF NOT EXISTS credential_id UUID;
"""


def iter_migration_sql() -> list[str]:
    return [MIGRATION_SQL, SOURCES_MIGRATION_SQL, CREDENTIALS_MIGRATION_SQL]


class PgMetaStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    def _conn(self):
        return psycopg.connect(self._dsn)

    @staticmethod
    def _set_tenant(conn: psycopg.Connection, tenant: str) -> None:
        # SET does not accept bind params; set_config does (RLS session var).
        conn.execute("SELECT set_config('app.tenant', %s, false)", (tenant,))

    def migrate(self) -> None:
        with self._conn() as conn:
            for stmt in iter_migration_sql():
                conn.execute(stmt)
            conn.commit()

    def upsert_document(
        self,
        tenant: str,
        doc_id: str,
        source_id: str,
        content_hash: str,
        s3_raw_uri: str,
        s3_parsed_uri: str,
        ingest_state: str = "pending",
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.documents
                    (tenant, id, source_id, content_hash, s3_raw_uri, s3_parsed_uri, ingest_state)
                VALUES (%s, %s::uuid, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant, id) DO UPDATE SET
                    s3_parsed_uri = EXCLUDED.s3_parsed_uri,
                    ingest_state = EXCLUDED.ingest_state
                """,
                (tenant, doc_id, source_id, content_hash, s3_raw_uri, s3_parsed_uri, ingest_state),
            )
            conn.commit()

    def upsert_chunks(self, tenant: str, chunks: list[ChunkRecord], s3_uri: str) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            for c in chunks:
                conn.execute(
                    """
                    INSERT INTO path_graph.chunks
                        (tenant, id, document_id, chunk_index, text, text_hash, s3_uri, qdrant_point_id)
                    VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant, id) DO UPDATE SET
                        text = EXCLUDED.text,
                        s3_uri = EXCLUDED.s3_uri,
                        qdrant_point_id = EXCLUDED.qdrant_point_id
                    """,
                    (
                        tenant,
                        c.chunk_id,
                        c.document_id,
                        c.chunk_index,
                        c.text,
                        c.text_hash,
                        s3_uri,
                        c.chunk_id,
                    ),
                )
            conn.commit()

    def mark_rag_indexed(self, tenant: str, document_id: str) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.document_ingest_state (tenant, document_id, rag_at)
                VALUES (%s, %s::uuid, now())
                ON CONFLICT (tenant, document_id) DO UPDATE SET rag_at = now()
                """,
                (tenant, document_id),
            )
            conn.execute(
                "UPDATE path_graph.documents SET ingest_state = 'indexed_rag' WHERE tenant = %s AND id = %s::uuid",
                (tenant, document_id),
            )
            conn.commit()

    def upsert_communities(self, records: list[CommunityRecord], s3_uri: str) -> None:
        if not records:
            return
        tenant = records[0].tenant
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            for rec in records:
                conn.execute(
                    """
                    INSERT INTO path_graph.communities
                        (tenant, project, id, batch_id, level, parent_id, title, s3_uri, entity_count)
                    VALUES (%s, %s, %s::uuid, %s, %s, %s::uuid, %s, %s, %s)
                    ON CONFLICT (tenant, project, id) DO UPDATE SET
                        s3_uri = EXCLUDED.s3_uri,
                        entity_count = EXCLUDED.entity_count,
                        level = EXCLUDED.level,
                        parent_id = EXCLUDED.parent_id
                    """,
                    (
                        rec.tenant,
                        rec.project,
                        rec.community_id,
                        rec.batch_id,
                        rec.level,
                        rec.parent_community_id,
                        None,
                        s3_uri,
                        rec.member_count,
                    ),
                )
            conn.commit()

    def upsert_wiki_page(
        self,
        tenant: str,
        project: int,
        slug: str,
        s3_uri: str,
        *,
        title: str | None = None,
        community_id: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.wiki_pages
                    (tenant, project, slug, title, s3_uri, community_id, batch_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::uuid, %s, now())
                ON CONFLICT (tenant, project, slug) DO UPDATE SET
                    title = EXCLUDED.title,
                    s3_uri = EXCLUDED.s3_uri,
                    community_id = EXCLUDED.community_id,
                    batch_id = EXCLUDED.batch_id,
                    updated_at = now()
                """,
                (tenant, project, slug, title, s3_uri, community_id, batch_id),
            )
            conn.commit()

    def record_dead_letter(self, tenant: str, doc_id: str, error: dict[str, Any]) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                UPDATE path_graph.documents SET ingest_state = 'dead_letter' WHERE tenant = %s AND id = %s::uuid
                """,
                (tenant, doc_id),
            )
            conn.execute(
                """
                INSERT INTO path_graph.document_ingest_state (tenant, document_id, error)
                VALUES (%s, %s::uuid, %s::jsonb)
                ON CONFLICT (tenant, document_id) DO UPDATE SET error = EXCLUDED.error
                """,
                (tenant, doc_id, json.dumps(error)),
            )
            conn.commit()
