from path_graph.contracts.community import CommunityRecord
from path_graph.graph.graph_context import build_graph_context
from path_graph.graph.nebula_store import NebulaGraphStore
from constants import PROJECT_ID


def test_build_graph_context_from_memory():
    memory: dict = {}
    nebula = NebulaGraphStore("h", 1, "u", "p", memory=memory)
    space = "path_graph_dev_default"
    nebula.ensure_space(space)
    nebula.upsert_entities(
        space,
        [
            {"id": "entity:Alice", "name": "Alice", "description": "Founder"},
            {"id": "entity:Bob", "name": "Bob", "description": "Engineer"},
        ],
    )
    nebula.upsert_edges(
        space,
        [
            {
                "type": "EXTRACTED",
                "source": "entity:Alice",
                "target": "entity:Bob",
                "confidence": 1.0,
                "description": "employs",
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
        entity_ids=["entity:Alice", "entity:Bob"],
    )
    ctx = build_graph_context(rec, nebula)
    assert ctx["project_id"] == PROJECT_ID
    assert len(ctx["entities"]) == 2
    assert len(ctx["relationships"]) == 1
