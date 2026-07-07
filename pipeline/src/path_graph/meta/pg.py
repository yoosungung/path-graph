from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

import psycopg

from path_graph.contracts.community import CommunityRecord
from path_graph.contracts.schemas import ChunkRecord


def _escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


MIGRATION_SQL = """
CREATE SCHEMA IF NOT EXISTS path_graph;

CREATE TABLE IF NOT EXISTS path_graph.documents (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    source_id TEXT NOT NULL,
    project_id UUID NOT NULL,
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
    project_id UUID NOT NULL,
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    s3_uri TEXT,
    PRIMARY KEY (tenant, id)
);

CREATE TABLE IF NOT EXISTS path_graph.pipeline_runs (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    workflow_name TEXT NOT NULL,
    argo_uid TEXT,
    batch_id TEXT,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
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
    project_id UUID NOT NULL,
    slug TEXT NOT NULL,
    title TEXT,
    community_id UUID,
    batch_id TEXT,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (tenant, project_id, slug)
);

CREATE TABLE IF NOT EXISTS path_graph.communities (
    tenant TEXT NOT NULL,
    project_id UUID NOT NULL,
    id UUID NOT NULL,
    batch_id TEXT NOT NULL,
    level INT NOT NULL,
    parent_id UUID,
    title TEXT,
    s3_uri TEXT NOT NULL,
    entity_count INT,
    PRIMARY KEY (tenant, project_id, id)
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

PROJECTS_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS path_graph.projects (
    tenant TEXT NOT NULL,
    id UUID NOT NULL,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, id),
    UNIQUE (tenant, slug)
);

ALTER TABLE path_graph.projects ENABLE ROW LEVEL SECURITY;

ALTER TABLE path_graph.sources
    ADD COLUMN IF NOT EXISTS project_id UUID;

ALTER TABLE path_graph.documents
    ADD COLUMN IF NOT EXISTS project_id UUID;

ALTER TABLE path_graph.chunks
    ADD COLUMN IF NOT EXISTS project_id UUID;
"""

LEGACY_PROJECT_MIGRATION_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'path_graph' AND table_name = 'communities' AND column_name = 'project'
    ) THEN
        ALTER TABLE path_graph.communities RENAME COLUMN project TO project_legacy_int;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'path_graph' AND table_name = 'wiki_pages' AND column_name = 'project'
    ) THEN
        ALTER TABLE path_graph.wiki_pages RENAME COLUMN project TO project_legacy_int;
    END IF;
END $$;

ALTER TABLE path_graph.communities
    ADD COLUMN IF NOT EXISTS project_id UUID;

ALTER TABLE path_graph.wiki_pages
    ADD COLUMN IF NOT EXISTS project_id UUID;
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

RLS_POLICY_MIGRATION_SQL = """
ALTER TABLE path_graph.pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE path_graph.document_ingest_state ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
  tbl text;
BEGIN
  FOR tbl IN SELECT unnest(ARRAY[
    'documents', 'chunks', 'pipeline_runs', 'document_ingest_state',
    'wiki_pages', 'communities', 'sources', 'source_credentials', 'projects',
    'document_tombstones', 'purge_audit_log', 'reconcile_reports', 'stale_communities',
    'entities'
  ])
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'path_graph' AND table_name = tbl
    ) THEN
      EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON path_graph.%I', tbl);
      EXECUTE format(
        'CREATE POLICY tenant_isolation ON path_graph.%I '
        'USING (tenant = current_setting(''app.tenant'', true)) '
        'WITH CHECK (tenant = current_setting(''app.tenant'', true))',
        tbl
      );
    END IF;
  END LOOP;
END $$;
"""

PIPELINE_RUNS_PERSIST_MIGRATION_SQL = """
ALTER TABLE path_graph.pipeline_runs
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;
"""

PIPELINE_RUNS_KIND_MIGRATION_SQL = """
ALTER TABLE path_graph.pipeline_runs
    ADD COLUMN IF NOT EXISTS project_id UUID,
    ADD COLUMN IF NOT EXISTS run_kind TEXT NOT NULL DEFAULT 'ingest';

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_tenant_project
    ON path_graph.pipeline_runs (tenant, project_id);
"""

LIFECYCLE_MIGRATION_SQL = """
ALTER TABLE path_graph.documents
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS purge_reason TEXT,
    ADD COLUMN IF NOT EXISTS purge_after_at TIMESTAMPTZ;

ALTER TABLE path_graph.projects
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS purge_state TEXT;

CREATE TABLE IF NOT EXISTS path_graph.document_tombstones (
    tenant TEXT NOT NULL,
    project_id UUID NOT NULL,
    content_hash TEXT NOT NULL,
    document_id UUID NOT NULL,
    purged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    purged_by TEXT,
    reason TEXT,
    PRIMARY KEY (tenant, project_id, content_hash)
);

CREATE TABLE IF NOT EXISTS path_graph.purge_audit_log (
    tenant TEXT NOT NULL,
    project_id UUID NOT NULL,
    id UUID NOT NULL,
    scope TEXT NOT NULL,
    target_id TEXT NOT NULL,
    store TEXT NOT NULL,
    status TEXT NOT NULL,
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, id)
);

CREATE TABLE IF NOT EXISTS path_graph.reconcile_reports (
    tenant TEXT NOT NULL,
    project_id UUID NOT NULL,
    id UUID NOT NULL,
    qdrant_orphans_deleted INT NOT NULL DEFAULT 0,
    nebula_orphans_deleted INT NOT NULL DEFAULT 0,
    pg_missing_points INT NOT NULL DEFAULT 0,
    duration_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, id)
);

CREATE TABLE IF NOT EXISTS path_graph.stale_communities (
    tenant TEXT NOT NULL,
    project_id UUID NOT NULL,
    community_id UUID NOT NULL,
    trigger_document_id UUID,
    stale_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, project_id, community_id)
);

ALTER TABLE path_graph.document_tombstones ENABLE ROW LEVEL SECURITY;
ALTER TABLE path_graph.purge_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE path_graph.reconcile_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE path_graph.stale_communities ENABLE ROW LEVEL SECURITY;
"""


SOURCE_PROJECT_BACKFILL_MIGRATION_SQL = """
DO $$
DECLARE
  rec RECORD;
  default_id UUID;
BEGIN
  FOR rec IN
    SELECT DISTINCT tenant FROM (
      SELECT tenant FROM path_graph.sources WHERE project_id IS NULL
      UNION
      SELECT tenant FROM path_graph.documents WHERE project_id IS NULL
      UNION
      SELECT tenant FROM path_graph.chunks WHERE project_id IS NULL
    ) t
  LOOP
    SELECT id INTO default_id
    FROM path_graph.projects
    WHERE tenant = rec.tenant AND slug = 'default';

    IF default_id IS NULL THEN
      default_id := gen_random_uuid();
      INSERT INTO path_graph.projects (tenant, id, slug, name)
      VALUES (rec.tenant, default_id, 'default', 'Default');
    END IF;

    UPDATE path_graph.sources
    SET project_id = default_id, updated_at = now()
    WHERE tenant = rec.tenant AND project_id IS NULL;

    UPDATE path_graph.documents
    SET project_id = default_id
    WHERE tenant = rec.tenant AND project_id IS NULL;

    UPDATE path_graph.chunks
    SET project_id = default_id
    WHERE tenant = rec.tenant AND project_id IS NULL;
  END LOOP;
END $$;
"""

CHUNKS_FTS_MIGRATION_SQL = """
ALTER TABLE path_graph.chunks
    ADD COLUMN IF NOT EXISTS text_tsv tsvector;

UPDATE path_graph.chunks
SET text_tsv = to_tsvector('simple', coalesce(text, ''))
WHERE text_tsv IS NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_text_tsv
    ON path_graph.chunks USING GIN (text_tsv);
"""

PGVECTOR_MIGRATION_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE path_graph.chunks
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

ALTER TABLE path_graph.chunks DROP COLUMN IF EXISTS qdrant_point_id;

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON path_graph.chunks USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_tenant_project
    ON path_graph.chunks (tenant, project_id)
    WHERE embedding IS NOT NULL;

ALTER TABLE path_graph.reconcile_reports
    RENAME COLUMN qdrant_orphans_deleted TO vector_orphans_cleared;
"""

WIKI_PAGES_DROP_S3_URI_SQL = """
ALTER TABLE path_graph.wiki_pages DROP COLUMN IF EXISTS s3_uri;
"""

WIKI_SEARCH_MIGRATION_SQL = """
ALTER TABLE path_graph.wiki_pages
    ADD COLUMN IF NOT EXISTS vfs_path TEXT,
    ADD COLUMN IF NOT EXISTS body_text TEXT,
    ADD COLUMN IF NOT EXISTS text_tsv tsvector,
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

CREATE INDEX IF NOT EXISTS idx_wiki_pages_text_tsv
    ON path_graph.wiki_pages USING GIN (text_tsv);

CREATE INDEX IF NOT EXISTS idx_wiki_pages_embedding_hnsw
    ON path_graph.wiki_pages USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_wiki_pages_tenant_project
    ON path_graph.wiki_pages (tenant, project_id);
"""

ENTITIES_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS path_graph.entities (
    tenant TEXT NOT NULL,
    project_id UUID NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    name_tsv tsvector,
    embedding vector(1024),
    PRIMARY KEY (tenant, project_id, id)
);

CREATE INDEX IF NOT EXISTS idx_entities_name_tsv
    ON path_graph.entities USING GIN (name_tsv);

CREATE INDEX IF NOT EXISTS idx_entities_embedding_hnsw
    ON path_graph.entities USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

ALTER TABLE path_graph.entities ENABLE ROW LEVEL SECURITY;
"""

ENTITIES_RLS_MIGRATION_SQL = """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'path_graph' AND table_name = 'entities'
  ) THEN
    EXECUTE 'DROP POLICY IF EXISTS tenant_isolation ON path_graph.entities';
    EXECUTE
      'CREATE POLICY tenant_isolation ON path_graph.entities '
      'USING (tenant = current_setting(''app.tenant'', true)) '
      'WITH CHECK (tenant = current_setting(''app.tenant'', true))';
  END IF;
END $$;
"""


def iter_migration_sql() -> list[str]:
    return [
        MIGRATION_SQL,
        SOURCES_MIGRATION_SQL,
        CREDENTIALS_MIGRATION_SQL,
        PROJECTS_MIGRATION_SQL,
        LEGACY_PROJECT_MIGRATION_SQL,
        SOURCE_PROJECT_BACKFILL_MIGRATION_SQL,
        LIFECYCLE_MIGRATION_SQL,
        PIPELINE_RUNS_PERSIST_MIGRATION_SQL,
        PIPELINE_RUNS_KIND_MIGRATION_SQL,
        RLS_POLICY_MIGRATION_SQL,
        CHUNKS_FTS_MIGRATION_SQL,
        PGVECTOR_MIGRATION_SQL,
        WIKI_PAGES_DROP_S3_URI_SQL,
        WIKI_SEARCH_MIGRATION_SQL,
        ENTITIES_MIGRATION_SQL,
        ENTITIES_RLS_MIGRATION_SQL,
    ]


class PgMetaStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    def _conn(self):
        return psycopg.connect(self._dsn)

    def _vector_conn(self):
        conn = psycopg.connect(self._dsn)
        self._register_vector(conn)
        return conn

    @staticmethod
    def _register_vector(conn) -> None:
        from pgvector.psycopg import register_vector

        register_vector(conn)

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
        project_id: str,
        content_hash: str,
        s3_raw_uri: str,
        s3_parsed_uri: str,
        ingest_state: str = "pending",
    ) -> None:
        if self.is_tombstoned(tenant, project_id, content_hash):
            raise ValueError(f"tombstoned content_hash: {content_hash}")
        existing = self.get_document(tenant, doc_id)
        if existing and existing.get("ingest_state") == "purged":
            raise ValueError(f"document purged: {doc_id}")
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.documents
                    (tenant, id, source_id, project_id, content_hash, s3_raw_uri, s3_parsed_uri, ingest_state)
                VALUES (%s, %s::uuid, %s, %s::uuid, %s, %s, %s, %s)
                ON CONFLICT (tenant, id) DO UPDATE SET
                    s3_parsed_uri = EXCLUDED.s3_parsed_uri,
                    ingest_state = EXCLUDED.ingest_state,
                    project_id = EXCLUDED.project_id
                """,
                (
                    tenant,
                    doc_id,
                    source_id,
                    project_id,
                    content_hash,
                    s3_raw_uri,
                    s3_parsed_uri,
                    ingest_state,
                ),
            )
            conn.commit()

    def upsert_chunks(
        self,
        tenant: str,
        chunks: list[ChunkRecord],
        s3_uri: str,
        *,
        embeddings: Sequence[Sequence[float]] | None = None,
    ) -> None:
        if embeddings is not None and len(embeddings) != len(chunks):
            raise ValueError("embeddings length must match chunks")
        with self._vector_conn() as conn:
            self._set_tenant(conn, tenant)
            for idx, c in enumerate(chunks):
                if embeddings is not None:
                    conn.execute(
                        """
                        INSERT INTO path_graph.chunks
                            (tenant, id, document_id, project_id, chunk_index,
                             text, text_hash, s3_uri, text_tsv, embedding)
                        VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s,
                                to_tsvector('simple', %s), %s)
                        ON CONFLICT (tenant, id) DO UPDATE SET
                            text = EXCLUDED.text,
                            text_tsv = to_tsvector('simple', EXCLUDED.text),
                            s3_uri = EXCLUDED.s3_uri,
                            project_id = EXCLUDED.project_id,
                            embedding = EXCLUDED.embedding
                        """,
                        (
                            tenant,
                            c.chunk_id,
                            c.document_id,
                            c.project_id,
                            c.chunk_index,
                            c.text,
                            c.text_hash,
                            s3_uri,
                            c.text,
                            list(embeddings[idx]),
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO path_graph.chunks
                            (tenant, id, document_id, project_id, chunk_index,
                             text, text_hash, s3_uri, text_tsv)
                        VALUES (%s, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s,
                                to_tsvector('simple', %s))
                        ON CONFLICT (tenant, id) DO UPDATE SET
                            text = EXCLUDED.text,
                            text_tsv = to_tsvector('simple', EXCLUDED.text),
                            s3_uri = EXCLUDED.s3_uri,
                            project_id = EXCLUDED.project_id
                        """,
                        (
                            tenant,
                            c.chunk_id,
                            c.document_id,
                            c.project_id,
                            c.chunk_index,
                            c.text,
                            c.text_hash,
                            s3_uri,
                            c.text,
                        ),
                    )
            conn.commit()

    def search_vector(
        self,
        tenant: str,
        project_id: str,
        query_vector: Sequence[float],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._vector_conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT
                    c.id::text AS chunk_id,
                    c.document_id::text AS document_id,
                    c.project_id::text AS project_id,
                    c.text,
                    1 - (c.embedding <=> %s) AS score
                FROM path_graph.chunks c
                WHERE c.tenant = %s
                  AND c.project_id = %s::uuid
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> %s
                LIMIT %s
                """,
                (list(query_vector), tenant, project_id, list(query_vector), limit),
            ).fetchall()
        return [
            {
                "chunk_id": row[0],
                "document_id": row[1],
                "project_id": row[2],
                "text": row[3],
                "score": float(row[4]),
            }
            for row in rows
        ]

    def clear_embeddings_for_document(self, tenant: str, document_id: str) -> int:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                UPDATE path_graph.chunks
                SET embedding = NULL
                WHERE tenant = %s AND document_id = %s::uuid
                """,
                (tenant, document_id),
            )
            conn.commit()
            return cur.rowcount

    def clear_embeddings_for_chunks(
        self, tenant: str, chunk_ids: list[str]
    ) -> int:
        if not chunk_ids:
            return 0
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                UPDATE path_graph.chunks
                SET embedding = NULL
                WHERE tenant = %s AND id = ANY(%s::uuid[])
                """,
                (tenant, chunk_ids),
            )
            conn.commit()
            return cur.rowcount

    def clear_embeddings_for_project(self, tenant: str, project_id: str) -> int:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                UPDATE path_graph.chunks
                SET embedding = NULL
                WHERE tenant = %s AND project_id = %s::uuid
                """,
                (tenant, project_id),
            )
            conn.commit()
            return cur.rowcount

    def analyze_chunks_embeddings(self, tenant: str, project_id: str) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute("ANALYZE path_graph.chunks")
            conn.commit()

    def search_fts(
        self,
        tenant: str,
        project_id: str,
        query: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = query.strip()
        if not q:
            return []
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT
                    c.id::text AS chunk_id,
                    c.document_id::text AS document_id,
                    c.project_id::text AS project_id,
                    c.text,
                    ts_rank(c.text_tsv, q) AS rank
                FROM path_graph.chunks c,
                     plainto_tsquery('simple', %s) q
                WHERE c.tenant = %s
                  AND c.project_id = %s::uuid
                  AND c.text_tsv @@ q
                ORDER BY rank DESC
                LIMIT %s
                """,
                (q, tenant, project_id, limit),
            ).fetchall()
        return [
            {
                "chunk_id": row[0],
                "document_id": row[1],
                "project_id": row[2],
                "text": row[3],
                "score": float(row[4]),
            }
            for row in rows
        ]

    def search_wiki_fts(
        self,
        tenant: str,
        project_id: str,
        query: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = query.strip()
        if not q:
            return []
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT
                    w.slug,
                    w.title,
                    w.community_id::text,
                    w.vfs_path,
                    w.body_text,
                    w.batch_id,
                    ts_rank(w.text_tsv, q) AS rank
                FROM path_graph.wiki_pages w,
                     plainto_tsquery('simple', %s) q
                WHERE w.tenant = %s
                  AND w.project_id = %s::uuid
                  AND w.text_tsv @@ q
                ORDER BY rank DESC
                LIMIT %s
                """,
                (q, tenant, project_id, limit),
            ).fetchall()
        return [
            {
                "slug": row[0],
                "title": row[1],
                "community_id": row[2],
                "vfs_path": row[3],
                "body_text": row[4],
                "batch_id": row[5],
                "score": float(row[6]),
            }
            for row in rows
        ]

    def search_wiki_vector(
        self,
        tenant: str,
        project_id: str,
        query_vector: Sequence[float],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._vector_conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT
                    w.slug,
                    w.title,
                    w.community_id::text,
                    w.vfs_path,
                    w.body_text,
                    w.batch_id,
                    1 - (w.embedding <=> %s) AS score
                FROM path_graph.wiki_pages w
                WHERE w.tenant = %s
                  AND w.project_id = %s::uuid
                  AND w.embedding IS NOT NULL
                ORDER BY w.embedding <=> %s
                LIMIT %s
                """,
                (list(query_vector), tenant, project_id, list(query_vector), limit),
            ).fetchall()
        return [
            {
                "slug": row[0],
                "title": row[1],
                "community_id": row[2],
                "vfs_path": row[3],
                "body_text": row[4],
                "batch_id": row[5],
                "score": float(row[6]),
            }
            for row in rows
        ]

    def upsert_entities(
        self,
        tenant: str,
        project_id: str,
        entities: list[dict[str, Any]],
        *,
        embeddings: Sequence[Sequence[float]] | None = None,
    ) -> None:
        if not entities:
            return
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            for idx, ent in enumerate(entities):
                eid = str(ent.get("id") or "")
                name = str(ent.get("name") or "")
                if not eid:
                    continue
                description = str(ent.get("description") or "")
                search_text = f"{name}\n{description}".strip()
                emb = (
                    list(embeddings[idx])
                    if embeddings is not None and idx < len(embeddings)
                    else None
                )
                if emb is not None:
                    conn.execute(
                        """
                        INSERT INTO path_graph.entities
                            (tenant, project_id, id, name, description, name_tsv, embedding)
                        VALUES (%s, %s::uuid, %s, %s, %s, to_tsvector('simple', %s), %s)
                        ON CONFLICT (tenant, project_id, id) DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            name_tsv = to_tsvector('simple', %s),
                            embedding = EXCLUDED.embedding
                        """,
                        (
                            tenant,
                            project_id,
                            eid,
                            name,
                            description,
                            search_text,
                            emb,
                            search_text,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO path_graph.entities
                            (tenant, project_id, id, name, description, name_tsv)
                        VALUES (%s, %s::uuid, %s, %s, %s, to_tsvector('simple', %s))
                        ON CONFLICT (tenant, project_id, id) DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            name_tsv = to_tsvector('simple', %s)
                        """,
                        (
                            tenant,
                            project_id,
                            eid,
                            name,
                            description,
                            search_text,
                            search_text,
                        ),
                    )
            conn.commit()

    def search_entities_fts(
        self,
        tenant: str,
        project_id: str,
        query: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = query.strip()
        if not q:
            return []
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT e.id, e.name, e.description, ts_rank(e.name_tsv, q) AS rank
                FROM path_graph.entities e,
                     plainto_tsquery('simple', %s) q
                WHERE e.tenant = %s
                  AND e.project_id = %s::uuid
                  AND e.name_tsv @@ q
                ORDER BY rank DESC
                LIMIT %s
                """,
                (q, tenant, project_id, limit),
            ).fetchall()
        return [
            {
                "entity_id": row[0],
                "name": row[1],
                "description": row[2],
                "score": float(row[3]),
            }
            for row in rows
        ]

    def search_entities_vector(
        self,
        tenant: str,
        project_id: str,
        query_vector: Sequence[float],
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        with self._vector_conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT e.id, e.name, e.description, 1 - (e.embedding <=> %s) AS score
                FROM path_graph.entities e
                WHERE e.tenant = %s
                  AND e.project_id = %s::uuid
                  AND e.embedding IS NOT NULL
                ORDER BY e.embedding <=> %s
                LIMIT %s
                """,
                (list(query_vector), tenant, project_id, list(query_vector), limit),
            ).fetchall()
        return [
            {
                "entity_id": row[0],
                "name": row[1],
                "description": row[2],
                "score": float(row[3]),
            }
            for row in rows
        ]

    def get_chunks_by_ids(
        self,
        tenant: str,
        project_id: str,
        chunk_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT c.id::text, c.document_id::text, c.project_id::text, c.text
                FROM path_graph.chunks c
                WHERE c.tenant = %s
                  AND c.project_id = %s::uuid
                  AND c.id = ANY(%s::uuid[])
                """,
                (tenant, project_id, chunk_ids),
            ).fetchall()
        return [
            {
                "chunk_id": row[0],
                "document_id": row[1],
                "project_id": row[2],
                "text": row[3],
            }
            for row in rows
        ]

    def get_community(
        self,
        tenant: str,
        project_id: str,
        community_id: str,
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                SELECT id::text, batch_id, level, s3_uri, title
                FROM path_graph.communities
                WHERE tenant = %s AND project_id = %s::uuid AND id = %s::uuid
                """,
                (tenant, project_id, community_id),
            ).fetchone()
        if not row:
            return None
        return {
            "community_id": row[0],
            "batch_id": row[1],
            "level": row[2],
            "s3_uri": row[3],
            "title": row[4],
        }

    def stale_community_ids(self, tenant: str, project_id: str) -> set[str]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT community_id::text
                FROM path_graph.stale_communities
                WHERE tenant = %s AND project_id = %s::uuid
                """,
                (tenant, project_id),
            ).fetchall()
        return {row[0] for row in rows if row[0]}

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

    def mark_graphrag_indexed(self, tenant: str, document_ids: list[str]) -> int:
        if not document_ids:
            return 0
        updated = 0
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            for document_id in document_ids:
                conn.execute(
                    """
                    INSERT INTO path_graph.document_ingest_state
                        (tenant, document_id, graph_at, wiki_at)
                    VALUES (%s, %s::uuid, now(), now())
                    ON CONFLICT (tenant, document_id) DO UPDATE SET
                        graph_at = now(),
                        wiki_at = now()
                    """,
                    (tenant, document_id),
                )
                cur = conn.execute(
                    """
                    UPDATE path_graph.documents
                    SET ingest_state = 'indexed_graph'
                    WHERE tenant = %s AND id = %s::uuid
                    """,
                    (tenant, document_id),
                )
                updated += cur.rowcount
            conn.commit()
        return updated

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
                        (tenant, project_id, id, batch_id, level, parent_id, title, s3_uri, entity_count)
                    VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s::uuid, %s, %s, %s)
                    ON CONFLICT (tenant, project_id, id) DO UPDATE SET
                        s3_uri = EXCLUDED.s3_uri,
                        entity_count = EXCLUDED.entity_count,
                        level = EXCLUDED.level,
                        parent_id = EXCLUDED.parent_id
                    """,
                    (
                        rec.tenant,
                        rec.project_id,
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
        project_id: str,
        slug: str,
        *,
        title: str | None = None,
        community_id: str | None = None,
        batch_id: str | None = None,
        vfs_path: str | None = None,
        body_text: str | None = None,
        embedding: Sequence[float] | None = None,
    ) -> None:
        search_text = ""
        if title:
            search_text = title.strip()
        if body_text:
            body = body_text.strip()
            search_text = f"{search_text}\n{body}".strip() if search_text else body
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            if embedding is not None:
                conn.execute(
                    """
                    INSERT INTO path_graph.wiki_pages
                        (tenant, project_id, slug, title, community_id, batch_id,
                         vfs_path, body_text, text_tsv, embedding, updated_at)
                    VALUES (%s, %s::uuid, %s, %s, %s::uuid, %s, %s, %s,
                            to_tsvector('simple', %s), %s, now())
                    ON CONFLICT (tenant, project_id, slug) DO UPDATE SET
                        title = EXCLUDED.title,
                        community_id = EXCLUDED.community_id,
                        batch_id = EXCLUDED.batch_id,
                        vfs_path = EXCLUDED.vfs_path,
                        body_text = EXCLUDED.body_text,
                        text_tsv = to_tsvector('simple', %s),
                        embedding = EXCLUDED.embedding,
                        updated_at = now()
                    """,
                    (
                        tenant,
                        project_id,
                        slug,
                        title,
                        community_id,
                        batch_id,
                        vfs_path,
                        body_text,
                        search_text,
                        list(embedding),
                        search_text,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO path_graph.wiki_pages
                        (tenant, project_id, slug, title, community_id, batch_id,
                         vfs_path, body_text, text_tsv, updated_at)
                    VALUES (%s, %s::uuid, %s, %s, %s::uuid, %s, %s, %s,
                            to_tsvector('simple', %s), now())
                    ON CONFLICT (tenant, project_id, slug) DO UPDATE SET
                        title = EXCLUDED.title,
                        community_id = EXCLUDED.community_id,
                        batch_id = EXCLUDED.batch_id,
                        vfs_path = EXCLUDED.vfs_path,
                        body_text = EXCLUDED.body_text,
                        text_tsv = to_tsvector('simple', %s),
                        updated_at = now()
                    """,
                    (
                        tenant,
                        project_id,
                        slug,
                        title,
                        community_id,
                        batch_id,
                        vfs_path,
                        body_text,
                        search_text,
                        search_text,
                    ),
                )
            conn.commit()

    def get_document(self, tenant: str, document_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                SELECT id::text, source_id, project_id::text, content_hash,
                       s3_raw_uri, s3_parsed_uri, ingest_state, deleted_at
                FROM path_graph.documents
                WHERE tenant = %s AND id = %s::uuid
                """,
                (tenant, document_id),
            ).fetchone()
        if not row:
            return None
        return {
            "document_id": row[0],
            "source_id": row[1],
            "project_id": row[2],
            "content_hash": row[3],
            "s3_raw_uri": row[4],
            "s3_parsed_uri": row[5],
            "ingest_state": row[6],
            "deleted_at": row[7],
        }

    def list_documents_for_project(
        self,
        tenant: str,
        project_id: str,
        *,
        source_id: str | None = None,
        ingest_state: str | None = None,
        filename_contains: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            clauses = ["tenant = %s", "project_id = %s::uuid"]
            params: list[Any] = [tenant, project_id]
            if source_id:
                clauses.append("source_id = %s")
                params.append(source_id)
            if ingest_state:
                clauses.append("ingest_state = %s")
                params.append(ingest_state)
            if filename_contains:
                clauses.append("s3_raw_uri ILIKE %s ESCAPE '\\'")
                params.append(f"%{_escape_ilike(filename_contains)}%")
            where = " AND ".join(clauses)
            paging = ""
            if limit is not None:
                paging = " LIMIT %s OFFSET %s"
                params.extend([limit, offset])
            rows = conn.execute(
                f"""
                SELECT id::text, source_id, project_id::text, content_hash,
                       s3_raw_uri, ingest_state
                FROM path_graph.documents
                WHERE {where}
                ORDER BY id DESC
                {paging}
                """,
                params,
            ).fetchall()
        return [
            {
                "document_id": r[0],
                "source_id": r[1],
                "project_id": r[2],
                "content_hash": r[3],
                "s3_raw_uri": r[4],
                "ingest_state": r[5],
            }
            for r in rows
        ]

    def count_documents_for_project(
        self,
        tenant: str,
        project_id: str,
        *,
        source_id: str | None = None,
        ingest_state: str | None = None,
        filename_contains: str | None = None,
    ) -> int:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            clauses = ["tenant = %s", "project_id = %s::uuid"]
            params: list[Any] = [tenant, project_id]
            if source_id:
                clauses.append("source_id = %s")
                params.append(source_id)
            if ingest_state:
                clauses.append("ingest_state = %s")
                params.append(ingest_state)
            if filename_contains:
                clauses.append("s3_raw_uri ILIKE %s ESCAPE '\\'")
                params.append(f"%{_escape_ilike(filename_contains)}%")
            where = " AND ".join(clauses)
            row = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM path_graph.documents
                WHERE {where}
                """,
                params,
            ).fetchone()
        return int(row[0]) if row else 0

    def list_chunk_ids_for_document(self, tenant: str, document_id: str) -> list[str]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT id::text FROM path_graph.chunks
                WHERE tenant = %s AND document_id = %s::uuid
                ORDER BY chunk_index
                """,
                (tenant, document_id),
            ).fetchall()
        return [r[0] for r in rows]

    def list_active_chunk_ids(self, tenant: str, project_id: str) -> set[str]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT c.id::text
                FROM path_graph.chunks c
                JOIN path_graph.documents d
                  ON d.tenant = c.tenant AND d.id = c.document_id
                WHERE c.tenant = %s AND c.project_id = %s::uuid
                  AND d.ingest_state NOT IN ('purged', 'purging')
                """,
                (tenant, project_id),
            ).fetchall()
        return {r[0] for r in rows}

    def set_document_ingest_state(
        self, tenant: str, document_id: str, ingest_state: str
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                UPDATE path_graph.documents
                SET ingest_state = %s
                WHERE tenant = %s AND id = %s::uuid
                """,
                (ingest_state, tenant, document_id),
            )
            conn.commit()

    def mark_document_purged(
        self,
        tenant: str,
        document_id: str,
        *,
        reason: str | None = None,
        purge_after_at: Any = None,
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                UPDATE path_graph.documents
                SET ingest_state = 'purged',
                    deleted_at = now(),
                    purge_reason = %s,
                    purge_after_at = %s
                WHERE tenant = %s AND id = %s::uuid
                """,
                (reason, purge_after_at, tenant, document_id),
            )
            conn.commit()

    def delete_chunks_for_document(self, tenant: str, document_id: str) -> int:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                DELETE FROM path_graph.chunks
                WHERE tenant = %s AND document_id = %s::uuid
                """,
                (tenant, document_id),
            )
            conn.commit()
            return cur.rowcount

    def is_tombstoned(self, tenant: str, project_id: str, content_hash: str) -> bool:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                SELECT 1 FROM path_graph.document_tombstones
                WHERE tenant = %s AND project_id = %s::uuid AND content_hash = %s
                """,
                (tenant, project_id, content_hash),
            ).fetchone()
        return row is not None

    def insert_tombstone(
        self,
        tenant: str,
        project_id: str,
        content_hash: str,
        document_id: str,
        *,
        reason: str | None = None,
        purged_by: str | None = None,
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.document_tombstones
                    (tenant, project_id, content_hash, document_id, reason, purged_by)
                VALUES (%s, %s::uuid, %s, %s::uuid, %s, %s)
                ON CONFLICT (tenant, project_id, content_hash) DO NOTHING
                """,
                (tenant, project_id, content_hash, document_id, reason, purged_by),
            )
            conn.commit()

    def clear_tombstone(self, tenant: str, project_id: str, content_hash: str) -> bool:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                DELETE FROM path_graph.document_tombstones
                WHERE tenant = %s AND project_id = %s::uuid AND content_hash = %s
                """,
                (tenant, project_id, content_hash),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_tombstones(
        self, tenant: str, *, project_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            if project_id:
                rows = conn.execute(
                    """
                    SELECT project_id::text, content_hash, document_id::text,
                           purged_at, reason
                    FROM path_graph.document_tombstones
                    WHERE tenant = %s AND project_id = %s::uuid
                    ORDER BY purged_at DESC
                    LIMIT %s
                    """,
                    (tenant, project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT project_id::text, content_hash, document_id::text,
                           purged_at, reason
                    FROM path_graph.document_tombstones
                    WHERE tenant = %s
                    ORDER BY purged_at DESC
                    LIMIT %s
                    """,
                    (tenant, limit),
                ).fetchall()
        return [
            {
                "project_id": r[0],
                "content_hash": r[1],
                "document_id": r[2],
                "purged_at": r[3],
                "reason": r[4],
            }
            for r in rows
        ]

    def insert_purge_audit(
        self,
        tenant: str,
        project_id: str,
        scope: str,
        target_id: str,
        store: str,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> str:
        log_id = str(uuid.uuid4())
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.purge_audit_log
                    (tenant, project_id, id, scope, target_id, store, status, detail)
                VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    tenant,
                    project_id,
                    log_id,
                    scope,
                    target_id,
                    store,
                    status,
                    json.dumps(detail or {}),
                ),
            )
            conn.commit()
        return log_id

    def insert_reconcile_report(
        self,
        tenant: str,
        project_id: str,
        *,
        vector_orphans_cleared: int,
        nebula_orphans_deleted: int,
        pg_missing_points: int,
        duration_ms: int,
    ) -> str:
        report_id = str(uuid.uuid4())
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.reconcile_reports
                    (tenant, project_id, id, vector_orphans_cleared,
                     nebula_orphans_deleted, pg_missing_points, duration_ms)
                VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s)
                """,
                (
                    tenant,
                    project_id,
                    report_id,
                    vector_orphans_cleared,
                    nebula_orphans_deleted,
                    pg_missing_points,
                    duration_ms,
                ),
            )
            conn.commit()
        return report_id

    def mark_stale_community(
        self,
        tenant: str,
        project_id: str,
        community_id: str,
        *,
        trigger_document_id: str | None = None,
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.stale_communities
                    (tenant, project_id, community_id, trigger_document_id, stale_at)
                VALUES (%s, %s::uuid, %s::uuid, %s::uuid, now())
                ON CONFLICT (tenant, project_id, community_id) DO UPDATE SET
                    trigger_document_id = EXCLUDED.trigger_document_id,
                    stale_at = now()
                """,
                (tenant, project_id, community_id, trigger_document_id),
            )
            conn.commit()

    def list_stale_communities(
        self, tenant: str, project_id: str
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT community_id::text, trigger_document_id::text, stale_at
                FROM path_graph.stale_communities
                WHERE tenant = %s AND project_id = %s::uuid
                ORDER BY stale_at DESC
                """,
                (tenant, project_id),
            ).fetchall()
        return [
            {
                "community_id": r[0],
                "trigger_document_id": r[1],
                "stale_at": r[2],
            }
            for r in rows
        ]

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

    def delete_project_data(self, tenant: str, project_id: str) -> dict[str, int]:
        """Hard-delete all PG rows scoped to a project (sources, documents, audit, project)."""
        counts: dict[str, int] = {}
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                DELETE FROM path_graph.document_ingest_state
                WHERE tenant = %s AND document_id IN (
                    SELECT id FROM path_graph.documents
                    WHERE tenant = %s AND project_id = %s::uuid
                )
                """,
                (tenant, tenant, project_id),
            )
            counts["document_ingest_state"] = cur.rowcount
            for table in (
                "chunks",
                "documents",
                "document_tombstones",
                "purge_audit_log",
                "reconcile_reports",
                "stale_communities",
                "wiki_pages",
                "communities",
                "sources",
                "pipeline_runs",
                "projects",
            ):
                if table == "projects":
                    clause = "tenant = %s AND id = %s::uuid"
                else:
                    clause = "tenant = %s AND project_id = %s::uuid"
                cur = conn.execute(
                    f"DELETE FROM path_graph.{table} WHERE {clause}",
                    (tenant, project_id),
                )
                counts[table] = cur.rowcount
            conn.commit()
        return counts
