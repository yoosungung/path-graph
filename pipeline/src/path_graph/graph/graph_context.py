from __future__ import annotations

from path_graph.contracts.community import CommunityRecord
from path_graph.contracts.s3_keys import s3_key_graph_context
from path_graph.graph.nebula_store import NebulaGraphStore
from path_graph.ids import nebula_space_name


def build_graph_context(
    record: CommunityRecord,
    nebula: NebulaGraphStore,
    *,
    max_entities: int = 50,
    source_chunk_ids: list[str] | None = None,
) -> dict:
    space = record.nebula_space or nebula_space_name(record.tenant, record.project_slug)
    entity_ids = record.entity_ids[:max_entities]
    entity_id_set = set(entity_ids)
    entities = nebula.get_entities(space, entity_ids)
    relationships = nebula.get_relationships(space, entity_id_set)
    return {
        "community_id": record.community_id,
        "tenant": record.tenant,
        "project_id": record.project_id,
        "project_slug": record.project_slug,
        "batch_id": record.batch_id,
        "level": record.level,
        "nebula_space": space,
        "entities": [
            {
                "id": ent.get("id", ""),
                "name": ent.get("name", ""),
                "description": ent.get("description", ""),
            }
            for ent in entities
        ],
        "relationships": [
            {
                "source": rel.get("source", ""),
                "target": rel.get("target", ""),
                "type": rel.get("type", "EXTRACTED"),
                "description": rel.get("description", ""),
            }
            for rel in relationships
        ],
        "source_chunk_ids": source_chunk_ids or [],
    }


def graph_context_key_for(record: CommunityRecord) -> str:
    return s3_key_graph_context(
        record.tenant, record.project_id, record.batch_id, record.community_id
    )
