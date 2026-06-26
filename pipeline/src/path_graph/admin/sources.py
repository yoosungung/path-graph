from __future__ import annotations

import json
from typing import Any

import psycopg

from path_graph.admin.projects import ProjectStore
from path_graph.contracts.source import (
    SourceCreate,
    SourceProfile,
    SourceUpdate,
    new_source_id,
    row_to_profile,
)

TERMINAL_PIPELINE_RUN_STATUSES = frozenset({"Succeeded", "Failed", "Error"})


def _format_pipeline_run_ts(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    iso = value.isoformat()  # type: ignore[union-attr]
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    return iso


def _pipeline_run_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "workflow_name": row[1],
        "argo_uid": row[2],
        "batch_id": row[3],
        "status": row[4],
        "started_at": _format_pipeline_run_ts(row[5]),
        "ended_at": _format_pipeline_run_ts(row[6]),
    }


def _pipeline_run_row_with_tenant(row: tuple[Any, ...]) -> dict[str, Any]:
    return {"tenant": row[0], **_pipeline_run_row(row[1:])}


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
        tenant, id, project_id, name, driver, source_id, config, enabled, schedule_cron,
        credential_id, last_batch_id, last_run_at, last_run_status, created_at, updated_at
    """

    def list_sources(self, tenant: str) -> list[SourceProfile]:
        ProjectStore(self._dsn).backfill_orphan_project_ids(tenant)
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
                    (tenant, id, project_id, name, driver, source_id, config, enabled, schedule_cron, credential_id)
                VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s::jsonb, %s, %s, %s::uuid)
                RETURNING {self._SELECT_COLS}
                """,
                (
                    tenant,
                    sid,
                    body.project_id,
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
        limit: int | None = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            clauses = ["tenant = %s", "source_id = %s"]
            params: list[Any] = [tenant, source_id]
            if ingest_state:
                clauses.append("ingest_state = %s")
                params.append(ingest_state)
            where = " AND ".join(clauses)
            paging = ""
            if limit is not None:
                paging = " LIMIT %s OFFSET %s"
                params.extend([limit, offset])
            rows = conn.execute(
                f"""
                SELECT id::text, source_id, content_hash, ingest_state, s3_raw_uri
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
                "content_hash": r[2],
                "ingest_state": r[3],
                "s3_raw_uri": r[4],
            }
            for r in rows
        ]

    def count_documents_by_source(
        self,
        tenant: str,
        source_id: str,
        *,
        ingest_state: str | None = None,
    ) -> int:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            clauses = ["tenant = %s", "source_id = %s"]
            params: list[Any] = [tenant, source_id]
            if ingest_state:
                clauses.append("ingest_state = %s")
                params.append(ingest_state)
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

    _PIPELINE_RUN_COLS = """
        id::text, workflow_name, argo_uid, batch_id, status, started_at, ended_at
    """

    def get_pipeline_run_by_batch(
        self, tenant: str, batch_id: str
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                f"""
                SELECT {self._PIPELINE_RUN_COLS}
                FROM path_graph.pipeline_runs
                WHERE tenant = %s AND batch_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (tenant, batch_id),
            ).fetchone()
        if not row:
            return None
        return _pipeline_run_row(row)

    def list_pipeline_runs(
        self, tenant: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                f"""
                SELECT {self._PIPELINE_RUN_COLS}
                FROM path_graph.pipeline_runs
                WHERE tenant = %s
                ORDER BY started_at DESC NULLS LAST, id DESC
                LIMIT %s OFFSET %s
                """,
                (tenant, limit, offset),
            ).fetchall()
        return [_pipeline_run_row(r) for r in rows]

    def count_pipeline_runs(self, tenant: str) -> int:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM path_graph.pipeline_runs
                WHERE tenant = %s
                """,
                (tenant,),
            ).fetchone()
        return int(row[0]) if row else 0

    def list_non_finalized_pipeline_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return open runs across tenants (backend reconciler; table owner bypasses RLS)."""
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT tenant, {self._PIPELINE_RUN_COLS}
                FROM path_graph.pipeline_runs
                WHERE status NOT IN ('Succeeded', 'Failed', 'Error')
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [_pipeline_run_row_with_tenant(r) for r in rows]

    def finalize_pipeline_run(
        self,
        tenant: str,
        run_id: str,
        status: str,
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> bool:
        if status not in TERMINAL_PIPELINE_RUN_STATUSES:
            return False
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                UPDATE path_graph.pipeline_runs
                SET status = %s,
                    started_at = COALESCE(%s::timestamptz, started_at),
                    ended_at = COALESCE(%s::timestamptz, ended_at)
                WHERE tenant = %s
                  AND id = %s::uuid
                  AND status NOT IN ('Succeeded', 'Failed', 'Error')
                """,
                (status, started_at, ended_at, tenant, run_id),
            )
            conn.commit()
        return cur.rowcount > 0

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
