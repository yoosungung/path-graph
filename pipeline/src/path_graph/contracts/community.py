from __future__ import annotations

from pydantic import BaseModel, Field

from path_graph.contracts.s3_keys import s3_key_graph_context
from path_graph.ids import community_id as make_community_id
from path_graph.ids import nebula_space_name


class CommunityRecord(BaseModel):
    community_id: str
    tenant: str
    project_id: str
    project_slug: str
    batch_id: str
    level: int
    parent_community_id: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    member_count: int = 0
    nebula_space: str = ""
    graph_context_key: str = ""

    @classmethod
    def build(
        cls,
        *,
        tenant: str,
        project_id: str,
        project_slug: str,
        batch_id: str,
        level: int,
        cluster_key: str,
        entity_ids: list[str],
        parent_community_id: str | None = None,
    ) -> CommunityRecord:
        cid = make_community_id(tenant, project_id, batch_id, level, cluster_key)
        return cls(
            community_id=cid,
            tenant=tenant,
            project_id=project_id,
            project_slug=project_slug,
            batch_id=batch_id,
            level=level,
            parent_community_id=parent_community_id,
            entity_ids=entity_ids,
            member_count=len(entity_ids),
            nebula_space=nebula_space_name(tenant, project_slug),
            graph_context_key=s3_key_graph_context(tenant, project_id, batch_id, cid),
        )
