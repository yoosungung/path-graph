from path_graph.contracts.community import CommunityRecord
from path_graph.graph.entity_vid import entity_vid
from path_graph.graph.graph_context import build_graph_context
from path_graph.graph.nebula_store import NebulaGraphStore
from constants import PROJECT_ID


def _memory_nebula() -> NebulaGraphStore:
    return NebulaGraphStore("h", 1, "u", "p", memory={})


def test_build_graph_context_limits_entities_and_relationships():
    nebula = _memory_nebula()
    space = "path_graph_dev_default"
    nebula.ensure_space(space)
    entity_ids = [entity_vid(f"Entity-{i}") for i in range(5)]
    nebula.upsert_entities(
        space,
        [
            {
                "id": eid,
                "name": f"Entity-{i}",
                "description": "x" * 500,
            }
            for i, eid in enumerate(entity_ids)
        ],
    )
    for i in range(len(entity_ids) - 1):
        nebula.upsert_edges(
            space,
            [
                {
                    "type": "EXTRACTED",
                    "source": entity_ids[i],
                    "target": entity_ids[i + 1],
                    "confidence": 1.0,
                }
            ],
        )

    rec = CommunityRecord.build(
        tenant="dev",
        project_id=PROJECT_ID,
        project_slug="default",
        batch_id="b1",
        level=0,
        cluster_key="c0",
        entity_ids=entity_ids,
    )
    ctx = build_graph_context(
        rec,
        nebula,
        max_entities=2,
        max_relationships=1,
        max_description_chars=20,
    )
    assert len(ctx["entities"]) == 2
    assert all(len(ent["description"]) <= 20 for ent in ctx["entities"])
    assert len(ctx["relationships"]) == 1

