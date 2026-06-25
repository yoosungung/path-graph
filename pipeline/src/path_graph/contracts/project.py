from __future__ import annotations

import re
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from path_graph.contracts.s3_keys import s3_key_wiki_prefix
from path_graph.ids import nebula_space_name, normalize_project_slug, qdrant_collection_name


class ProjectProfile(BaseModel):
    tenant: str
    id: str
    slug: str
    name: str
    created_at: datetime | None = None

    @field_validator("tenant", "slug", "name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class ProjectCreate(BaseModel):
    name: str
    slug: str | None = None

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class ProjectUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class KnowledgeBindingRag(BaseModel):
    qdrant_collection: str
    filter: dict[str, str] = Field(default_factory=dict)


class KnowledgeBindingGraph(BaseModel):
    nebula_space: str


class KnowledgeBindingWiki(BaseModel):
    s3_prefix: str
    vfs_mount: str = "/wiki"


class KnowledgeBinding(BaseModel):
    tenant: str
    project_id: str
    project_slug: str
    rag: KnowledgeBindingRag
    graph: KnowledgeBindingGraph
    wiki: KnowledgeBindingWiki


def slug_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_")
    if not slug:
        raise ValueError("invalid project slug from name")
    return normalize_project_slug(slug)


def resolve_knowledge_binding(tenant: str, project_id: str, project_slug: str) -> KnowledgeBinding:
    if not tenant:
        raise ValueError("tenant is required")
    if not project_id:
        raise ValueError("project_id is required")
    slug = normalize_project_slug(project_slug)
    collection = qdrant_collection_name(tenant, slug)
    space = nebula_space_name(tenant, slug)
    return KnowledgeBinding(
        tenant=tenant,
        project_id=project_id,
        project_slug=slug,
        rag=KnowledgeBindingRag(
            qdrant_collection=collection,
            filter={"project_id": project_id},
        ),
        graph=KnowledgeBindingGraph(nebula_space=space),
        wiki=KnowledgeBindingWiki(s3_prefix=s3_key_wiki_prefix(tenant, project_id)),
    )


def row_to_project(row: tuple) -> ProjectProfile:
    tenant, pid, slug, name, created_at = row
    return ProjectProfile(
        tenant=tenant,
        id=str(pid) if not isinstance(pid, str) else pid,
        slug=slug,
        name=name,
        created_at=created_at,
    )


def new_project_id() -> str:
    return str(uuid4())
