"""Sync Postgres writer for pipeline wiki pages (vfs_wiki_files)."""

from __future__ import annotations

from typing import Any

import psycopg

from path_graph.config import Settings, get_settings


def normalize_path(path: str) -> str:
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    while "//" in path:
        path = path.replace("//", "/")
    return path or "/"


def normalize_dir(path: str) -> str:
    path = normalize_path(path)
    if path == "/":
        return "/"
    return path.rstrip("/") + "/"


def vfs_entry_metadata(path: str, content: bytes, *, is_dir: bool = False) -> tuple[str, str, int]:
    norm = normalize_path(path)
    trimmed = norm.rstrip("/")
    if trimmed == "" or trimmed == "/":
        return "/", "", 0
    if "/" in trimmed[1:]:
        parent, name = trimmed.rsplit("/", 1)
        parent_path = parent + "/"
    else:
        parent_path, name = "/", trimmed.lstrip("/")
    size = 0 if is_dir else len(content)
    return parent_path, name, size


def ancestor_dir_paths(parent_path: str) -> list[str]:
    current = normalize_dir(parent_path)
    dirs: list[str] = []
    while current != "/":
        dirs.append(current)
        trimmed = current.rstrip("/")
        if "/" not in trimmed[1:]:
            break
        parent, _ = trimmed.rsplit("/", 1)
        current = normalize_dir(parent)
    return dirs


def dir_row_fields(dir_path: str) -> tuple[str, str, str, int]:
    norm = normalize_dir(dir_path)
    parent_path, name, size = vfs_entry_metadata(norm, b"", is_dir=True)
    return norm, parent_path, name, size


def wiki_vfs_path_for_slug(slug: str) -> str:
    return normalize_path(f"/{slug}.md")


def _ensure_wiki_dirs(
    cur: Any, tenant: str, project_id: str, parent_path: str
) -> None:
    for dir_path in ancestor_dir_paths(parent_path):
        path, p_path, name, _ = dir_row_fields(dir_path)
        cur.execute(
            """
            INSERT INTO vfs_wiki_files (
                tenant, project_id, path, parent_path, name, is_dir, size, content, encoding
            )
            VALUES (%s, %s::uuid, %s, %s, %s, TRUE, 0, '\\x'::bytea, 'utf-8')
            ON CONFLICT (tenant, project_id, path) DO NOTHING
            """,
            (tenant, project_id, path, p_path, name),
        )


def write_wiki_page(
    tenant: str,
    project_id: str,
    slug: str,
    content: str,
    *,
    settings: Settings | None = None,
    conn: psycopg.Connection | None = None,
) -> str:
    """Upsert wiki markdown into vfs_wiki_files. Returns vfs path."""
    settings = settings or get_settings()
    path = wiki_vfs_path_for_slug(slug)
    encoded = content.encode("utf-8")
    parent_path, name, size = vfs_entry_metadata(path, encoded)

    def _write(c: psycopg.Cursor) -> None:
        _ensure_wiki_dirs(c, tenant, project_id, parent_path)
        c.execute(
            """
            INSERT INTO vfs_wiki_files (
                tenant, project_id, path, parent_path, name, is_dir, size, content, encoding
            )
            VALUES (%s, %s::uuid, %s, %s, %s, FALSE, %s, %s, 'utf-8')
            ON CONFLICT (tenant, project_id, path)
            DO UPDATE SET
                content = EXCLUDED.content,
                parent_path = EXCLUDED.parent_path,
                name = EXCLUDED.name,
                size = EXCLUDED.size,
                modified_at = now()
            """,
            (tenant, project_id, path, parent_path, name, size, encoded),
        )

    if conn is not None:
        with conn.cursor() as cur:
            _write(cur)
        return path

    dsn = settings.path_graph_dsn
    if not dsn:
        raise RuntimeError("PATH_GRAPH_DSN required for wiki VFS write")
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cur:
            _write(cur)
        connection.commit()
    return path


def delete_project_wiki_tree(
    tenant: str,
    project_id: str,
    *,
    settings: Settings | None = None,
    conn: psycopg.Connection | None = None,
) -> int:
    """Delete all vfs_wiki_files rows for a project. Returns deleted row count."""

    def _delete(c: psycopg.Cursor) -> int:
        c.execute(
            """
            DELETE FROM vfs_wiki_files
            WHERE tenant = %s AND project_id = %s::uuid
            """,
            (tenant, project_id),
        )
        return c.rowcount

    if conn is not None:
        with conn.cursor() as cur:
            return _delete(cur)

    settings = settings or get_settings()
    dsn = settings.path_graph_dsn
    if not dsn:
        raise RuntimeError("PATH_GRAPH_DSN required for wiki VFS delete")
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cur:
            count = _delete(cur)
        connection.commit()
    return count
