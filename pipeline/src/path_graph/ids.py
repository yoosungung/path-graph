from __future__ import annotations

import hashlib
import re
import uuid

PATH_GRAPH_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def document_id(tenant: str, content_hash: str) -> str:
    if not tenant:
        raise ValueError("tenant is required")
    return str(uuid.uuid5(PATH_GRAPH_NAMESPACE, f"{tenant}:{content_hash}"))


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


def tenant_project_index(partition_key: str, project_count: int) -> int:
    if project_count < 1:
        raise ValueError("project_count must be >= 1")
    digest = hashlib.sha256(partition_key.encode()).digest()
    return int.from_bytes(digest[:8], "big") % project_count


def qdrant_collection_name(tenant: str, project: int) -> str:
    if project < 0:
        raise ValueError("project must be >= 0")
    return f"path_graph_{normalize_tenant_slug(tenant)}_{project}"


def qdrant_collection_for_chunk(tenant: str, chunk_id_value: str, project_count: int) -> str:
    project = tenant_project_index(chunk_id_value, project_count)
    return qdrant_collection_name(tenant, project)


def nebula_space_name(tenant: str, project: int) -> str:
    if project < 0:
        raise ValueError("project must be >= 0")
    return f"path_graph_{normalize_tenant_slug(tenant)}_{project}"


def nebula_space_for_chunk(tenant: str, chunk_id_value: str, project_count: int) -> str:
    project = tenant_project_index(chunk_id_value, project_count)
    return nebula_space_name(tenant, project)


def community_id(
    tenant: str,
    project: int,
    batch_id: str,
    level: int,
    cluster_key: str,
) -> str:
    if not tenant:
        raise ValueError("tenant is required")
    if project < 0:
        raise ValueError("project must be >= 0")
    key = f"{tenant}:{project}:{batch_id}:{level}:{cluster_key}"
    return str(uuid.uuid5(PATH_GRAPH_NAMESPACE, key))


def wiki_slug_for_community(project: int, level: int, community_id_value: str) -> str:
    short = community_id_value.replace("-", "")[:8]
    return f"p{project}-community-L{level}-{short}"
