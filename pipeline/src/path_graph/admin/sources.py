from __future__ import annotations

import json
from typing import Any

import psycopg

from path_graph.contracts.source import (
    SourceCreate,
    SourceProfile,
    SourceUpdate,
    new_source_id,
    row_to_profile,
)


class SourceStore:
    """CRUD for path_graph.sources (tenant-scoped)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    def _conn(self):
        return psycopg.connect(self._dsn)

    @staticmethod
    def _set_tenant(conn: psycopg.Connection, tenant: str) -> None:
        conn.execute("SELECT set_config('app.tenant', %s, false)", (tenant,))

    _SELECT_COLS = """
        tenant, id, name, driver, source_id, config, enabled, schedule_cron,
        credential_id, last_batch_id, last_run_at, last_run_status, created_at, updated_at
    """

    def list_sources(self, tenant: str) -> list[SourceProfile]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM path_graph.sources
                WHERE tenant = %s
                ORDER BY name
                """,
                (tenant,),
            ).fetchall()
        return [row_to_profile(r) for r in rows]

    def get_source(self, tenant: str, source_uuid: str) -> SourceProfile | None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM path_graph.sources
                WHERE tenant = %s AND id = %s::uuid
                """,
                (tenant, source_uuid),
            ).fetchone()
        return row_to_profile(row) if row else None

    def create_source(self, tenant: str, body: SourceCreate) -> SourceProfile:
        sid = new_source_id()
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                f"""
                INSERT INTO path_graph.sources
                    (tenant, id, name, driver, source_id, config, enabled, schedule_cron, credential_id)
                VALUES (%s, %s::uuid, %s, %s, %s, %s::jsonb, %s, %s, %s::uuid)
                RETURNING {self._SELECT_COLS}
                """,
                (
                    tenant,
                    sid,
                    body.name,
                    body.driver.value,
                    body.source_id,
                    json.dumps(body.config),
                    body.enabled,
                    body.schedule_cron,
                    body.credential_id,
                ),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("insert failed")
        return row_to_profile(row)

    def update_source(
        self, tenant: str, source_uuid: str, body: SourceUpdate
    ) -> SourceProfile | None:
        existing = self.get_source(tenant, source_uuid)
        if existing is None:
            return None
        source_id = body.source_id if body.source_id is not None else existing.source_id
        config = body.config if body.config is not None else existing.config
        enabled = body.enabled if body.enabled is not None else existing.enabled
        schedule_cron = (
            body.schedule_cron if body.schedule_cron is not None else existing.schedule_cron
        )
        credential_id = (
            body.credential_id if body.credential_id is not None else existing.credential_id
        )
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                f"""
                UPDATE path_graph.sources
                SET source_id = %s,
                    config = %s::jsonb,
                    enabled = %s,
                    schedule_cron = %s,
                    credential_id = %s::uuid,
                    updated_at = now()
                WHERE tenant = %s AND id = %s::uuid
                RETURNING {self._SELECT_COLS}
                """,
                (
                    source_id,
                    json.dumps(config),
                    enabled,
                    schedule_cron,
                    credential_id,
                    tenant,
                    source_uuid,
                ),
            ).fetchone()
            conn.commit()
        return row_to_profile(row) if row else None

    def delete_source(self, tenant: str, source_uuid: str) -> bool:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                "DELETE FROM path_graph.sources WHERE tenant = %s AND id = %s::uuid",
                (tenant, source_uuid),
            )
            conn.commit()
            return cur.rowcount > 0

    def record_run(
        self,
        tenant: str,
        source_uuid: str,
        *,
        batch_id: str,
        status: str,
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                UPDATE path_graph.sources
                SET last_batch_id = %s,
                    last_run_at = now(),
                    last_run_status = %s,
                    updated_at = now()
                WHERE tenant = %s AND id = %s::uuid
                """,
                (batch_id, status, tenant, source_uuid),
            )
            conn.commit()

    def list_documents_summary(
        self, tenant: str, *, ingest_state: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            if ingest_state:
                rows = conn.execute(
                    """
                    SELECT id::text, source_id, content_hash, ingest_state, s3_raw_uri
                    FROM path_graph.documents
                    WHERE tenant = %s AND ingest_state = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (tenant, ingest_state, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id::text, source_id, content_hash, ingest_state, s3_raw_uri
                    FROM path_graph.documents
                    WHERE tenant = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (tenant, limit),
                ).fetchall()
        return [
            {
                "document_id": r[0],
                "source_id": r[1],
                "content_hash": r[2],
                "ingest_state": r[3],
                "s3_raw_uri": r[4],
            }
            for r in rows
        ]

    def list_documents_by_source(
        self,
        tenant: str,
        source_id: str,
        *,
        ingest_state: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            if ingest_state:
                rows = conn.execute(
                    """
                    SELECT id::text, source_id, content_hash, ingest_state, s3_raw_uri
                    FROM path_graph.documents
                    WHERE tenant = %s AND source_id = %s AND ingest_state = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (tenant, source_id, ingest_state, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id::text, source_id, content_hash, ingest_state, s3_raw_uri
                    FROM path_graph.documents
                    WHERE tenant = %s AND source_id = %s
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (tenant, source_id, limit),
                ).fetchall()
        return [
            {
                "document_id": r[0],
                "source_id": r[1],
                "content_hash": r[2],
                "ingest_state": r[3],
                "s3_raw_uri": r[4],
            }
            for r in rows
        ]

    def list_pipeline_runs(self, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT id::text, workflow_name, argo_uid, batch_id, status
                FROM path_graph.pipeline_runs
                WHERE tenant = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (tenant, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "workflow_name": r[1],
                "argo_uid": r[2],
                "batch_id": r[3],
                "status": r[4],
            }
            for r in rows
        ]

    def insert_pipeline_run(
        self,
        tenant: str,
        run_id: str,
        workflow_name: str,
        batch_id: str,
        status: str,
        argo_uid: str | None = None,
    ) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                INSERT INTO path_graph.pipeline_runs
                    (tenant, id, workflow_name, argo_uid, batch_id, status)
                VALUES (%s, %s::uuid, %s, %s, %s, %s)
                ON CONFLICT (tenant, id) DO UPDATE SET
                    status = EXCLUDED.status,
                    argo_uid = COALESCE(EXCLUDED.argo_uid, path_graph.pipeline_runs.argo_uid)
                """,
                (tenant, run_id, workflow_name, argo_uid, batch_id, status),
            )
            conn.commit()


def make_source_store(dsn: str | None = None) -> SourceStore:
    from path_graph.config import get_settings

    settings = get_settings()
    resolved = dsn or settings.path_graph_dsn
    if not resolved:
        raise ValueError("PATH_GRAPH_DSN is required")
    return SourceStore(resolved)
