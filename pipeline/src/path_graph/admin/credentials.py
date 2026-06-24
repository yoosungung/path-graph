from __future__ import annotations

import json
from typing import Any

import psycopg

from path_graph.contracts.credential import (
    CredentialCreate,
    CredentialProfile,
    OAuthStatus,
    k8s_secret_name_for_credential,
    new_credential_id,
    refresh_token_env_key,
    row_to_credential,
)
from path_graph.contracts.source import SourceDriver


class CredentialStore:
    """CRUD for path_graph.source_credentials (tenant-scoped, secrets in K8s only)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    def _conn(self):
        return psycopg.connect(self._dsn)

    @staticmethod
    def _set_tenant(conn: psycopg.Connection, tenant: str) -> None:
        conn.execute("SELECT set_config('app.tenant', %s, false)", (tenant,))

    _SELECT_COLS = """
        tenant, id, label, driver, config, secret_keys, oauth_status,
        k8s_secret_name, created_at, updated_at
    """

    def list_credentials(self, tenant: str) -> list[CredentialProfile]:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            rows = conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM path_graph.source_credentials
                WHERE tenant = %s
                ORDER BY label
                """,
                (tenant,),
            ).fetchall()
        return [row_to_credential(r) for r in rows]

    def get_credential(self, tenant: str, credential_id: str) -> CredentialProfile | None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM path_graph.source_credentials
                WHERE tenant = %s AND id = %s::uuid
                """,
                (tenant, credential_id),
            ).fetchone()
        return row_to_credential(row) if row else None

    def create_credential(self, tenant: str, body: CredentialCreate) -> CredentialProfile:
        cid = new_credential_id()
        secret_name = k8s_secret_name_for_credential(tenant, cid)
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                f"""
                INSERT INTO path_graph.source_credentials
                    (tenant, id, label, driver, config, k8s_secret_name)
                VALUES (%s, %s::uuid, %s, %s, %s::jsonb, %s)
                RETURNING {self._SELECT_COLS}
                """,
                (
                    tenant,
                    cid,
                    body.label,
                    body.driver.value,
                    json.dumps(body.config),
                    secret_name,
                ),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("insert failed")
        return row_to_credential(row)

    def delete_credential(self, tenant: str, credential_id: str) -> bool:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            cur = conn.execute(
                "DELETE FROM path_graph.source_credentials WHERE tenant = %s AND id = %s::uuid",
                (tenant, credential_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def mark_connected(
        self,
        tenant: str,
        credential_id: str,
        *,
        secret_keys: list[str] | None = None,
    ) -> CredentialProfile | None:
        keys = secret_keys
        if keys is None:
            cred = self.get_credential(tenant, credential_id)
            if cred is None:
                return None
            keys = [refresh_token_env_key(cred.driver)]
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            row = conn.execute(
                f"""
                UPDATE path_graph.source_credentials
                SET oauth_status = %s,
                    secret_keys = %s::text[],
                    updated_at = now()
                WHERE tenant = %s AND id = %s::uuid
                RETURNING {self._SELECT_COLS}
                """,
                (OAuthStatus.CONNECTED.value, keys, tenant, credential_id),
            ).fetchone()
            conn.commit()
        return row_to_credential(row) if row else None

    def mark_error(self, tenant: str, credential_id: str) -> None:
        with self._conn() as conn:
            self._set_tenant(conn, tenant)
            conn.execute(
                """
                UPDATE path_graph.source_credentials
                SET oauth_status = %s, updated_at = now()
                WHERE tenant = %s AND id = %s::uuid
                """,
                (OAuthStatus.ERROR.value, tenant, credential_id),
            )
            conn.commit()
