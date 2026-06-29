from __future__ import annotations

import psycopg

from path_graph.contracts.project import (
    ProjectCreate,
    ProjectProfile,
    ProjectUpdate,
    new_project_id,
    resolve_knowledge_binding,
    row_to_project,
    slug_from_name,
)
from path_graph.ids import normalize_project_slug


class ProjectStore:
    """CRUD for path_graph.projects (tenant-scoped)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    def _conn(self):
        return psycopg.connect(self._dsn)

    @staticmethod
    def _set_tenant(conn: psycopg.Connection, tenant: str) -> None:
        conn.execute("SELECT set_config('app.tenant', %s, false)", (tenant,))

    def list_projects(self, tenant: str) -> list[ProjectProfile]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                """
                SELECT tenant, id, slug, name, created_at
                FROM path_graph.projects
                WHERE tenant = %s
                ORDER BY name
                """,
                (tenant,),
            ).fetchall()
        return [row_to_project(r) for r in rows]

    def list_all_projects(self) -> list[ProjectProfile]:
        """Return all projects across tenants (backend bootstrap; table owner bypasses RLS)."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT tenant, id, slug, name, created_at
                FROM path_graph.projects
                ORDER BY tenant, name
                """
            ).fetchall()
        return [row_to_project(r) for r in rows]

    def get_project(self, tenant: str, project_id: str) -> ProjectProfile | None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                SELECT tenant, id, slug, name, created_at
                FROM path_graph.projects
                WHERE tenant = %s AND id = %s::uuid
                """,
                (tenant, project_id),
            ).fetchone()
        return row_to_project(row) if row else None

    def get_purge_state(self, tenant: str, project_id: str) -> str | None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                SELECT purge_state
                FROM path_graph.projects
                WHERE tenant = %s AND id = %s::uuid
                """,
                (tenant, project_id),
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    def set_purge_state(self, tenant: str, project_id: str, purge_state: str) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                UPDATE path_graph.projects
                SET purge_state = %s
                WHERE tenant = %s AND id = %s::uuid
                """,
                (purge_state, tenant, project_id),
            )
            conn.commit()

    def clear_in_progress_purge_state(self, tenant: str, project_id: str) -> bool:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                """
                UPDATE path_graph.projects
                SET purge_state = NULL
                WHERE tenant = %s AND id = %s::uuid
                  AND purge_state IN ('purging', 'deleting')
                """,
                (tenant, project_id),
            )
            conn.commit()
        return cur.rowcount > 0

    def get_project_by_slug(self, tenant: str, slug: str) -> ProjectProfile | None:
        normalized = normalize_project_slug(slug)
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                SELECT tenant, id, slug, name, created_at
                FROM path_graph.projects
                WHERE tenant = %s AND slug = %s
                """,
                (tenant, normalized),
            ).fetchone()
        return row_to_project(row) if row else None

    def create_project(self, tenant: str, body: ProjectCreate) -> ProjectProfile:
        pid = new_project_id()
        slug = normalize_project_slug(body.slug or slug_from_name(body.name))
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                INSERT INTO path_graph.projects (tenant, id, slug, name)
                VALUES (%s, %s::uuid, %s, %s)
                RETURNING tenant, id, slug, name, created_at
                """,
                (tenant, pid, slug, body.name.strip()),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("insert failed")
        return row_to_project(row)

    def update_project(
        self, tenant: str, project_id: str, body: ProjectUpdate
    ) -> ProjectProfile | None:
        existing = self.get_project(tenant, project_id)
        if existing is None:
            return None
        name = body.name.strip() if body.name is not None else existing.name
        slug = (
            normalize_project_slug(body.slug)
            if body.slug is not None
            else existing.slug
        )
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                """
                UPDATE path_graph.projects
                SET name = %s, slug = %s
                WHERE tenant = %s AND id = %s::uuid
                RETURNING tenant, id, slug, name, created_at
                """,
                (name, slug, tenant, project_id),
            ).fetchone()
            conn.commit()
        return row_to_project(row) if row else None

    def ensure_default_project(self, tenant: str) -> ProjectProfile:
        existing = self.get_project_by_slug(tenant, "default")
        if existing is not None:
            return existing
        return self.create_project(tenant, ProjectCreate(name="Default", slug="default"))

    def backfill_orphan_project_ids(self, tenant: str) -> int:
        """Assign tenant default project to rows missing project_id (legacy data)."""
        default = self.ensure_default_project(tenant)
        updated = 0
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            for table in ("sources", "documents", "chunks"):
                cur = conn.execute(
                    f"""
                    UPDATE path_graph.{table}
                    SET project_id = %s::uuid
                    WHERE tenant = %s AND project_id IS NULL
                    """,
                    (default.id, tenant),
                )
                updated += cur.rowcount
            if updated:
                conn.execute(
                    """
                    UPDATE path_graph.sources
                    SET updated_at = now()
                    WHERE tenant = %s AND project_id = %s::uuid
                    """,
                    (tenant, default.id),
                )
            conn.commit()
        return updated

    def resolve_binding(self, tenant: str, project_id: str):
        profile = self.get_project(tenant, project_id)
        if profile is None:
            raise ValueError(f"project not found: {project_id}")
        return resolve_knowledge_binding(tenant, profile.id, profile.slug)
