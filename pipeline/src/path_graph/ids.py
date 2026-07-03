from __future__ import annotations

import hashlib
import re
import uuid

PATH_GRAPH_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def document_id(tenant: str, project_id: str, content_hash: str) -> str:
    if not tenant:
        raise ValueError("tenant is required")
    if not project_id:
        raise ValueError("project_id is required")
    return str(uuid.uuid5(PATH_GRAPH_NAMESPACE, f"{tenant}:{project_id}:{content_hash}"))


def chunk_id(
    tenant: str,
    document_id_value: str,
    chunk_index: int,
    chunk_text_hash: str,
) -> str:
    if not tenant:
        raise ValueError("tenant is required")
    key = f"{tenant}:{document_id_value}:{chunk_index}:{chunk_text_hash}"
    return str(uuid.uuid5(PATH_GRAPH_NAMESPACE, key))


def normalize_tenant_slug(tenant: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", tenant.lower()).strip("_")
    if not slug:
        raise ValueError("invalid tenant slug")
    return slug


def normalize_project_slug(project_slug: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", project_slug.lower()).strip("_")
    if not slug:
        raise ValueError("invalid project slug")
    return slug


def index_namespace(tenant: str, project_slug: str) -> str:
    return f"path_graph_{normalize_tenant_slug(tenant)}_{normalize_project_slug(project_slug)}"


def nebula_space_name(tenant: str, project_slug: str) -> str:
    return index_namespace(tenant, project_slug)


def community_id(
    tenant: str,
    project_id: str,
    batch_id: str,
    level: int,
    cluster_key: str,
) -> str:
    if not tenant:
        raise ValueError("tenant is required")
    if not project_id:
        raise ValueError("project_id is required")
    key = f"{tenant}:{project_id}:{batch_id}:{level}:{cluster_key}"
    return str(uuid.uuid5(PATH_GRAPH_NAMESPACE, key))


def wiki_slug_for_community(project_slug: str, level: int, community_id_value: str) -> str:
    short = community_id_value.replace("-", "")[:8]
    slug = normalize_project_slug(project_slug)
    return f"{slug}-community-L{level}-{short}"
