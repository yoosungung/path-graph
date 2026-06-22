import pytest

from path_graph.graph.community_detector import detect_communities


def test_detect_communities_empty():
    assert detect_communities([]) == []


def test_detect_communities_triangle():
    edges = [
        ("entity:A", "entity:B", 1.0),
        ("entity:B", "entity:C", 1.0),
        ("entity:A", "entity:C", 1.0),
    ]
    clusters = detect_communities(edges, max_cluster_size=10, use_lcc=True, seed=0xDEADBEEF)
    assert clusters
    all_entities = {e for c in clusters for e in c.entity_ids}
    assert all_entities == {"entity:A", "entity:B", "entity:C"}


def test_detect_communities_two_components_use_lcc():
    edges = [
        ("entity:A", "entity:B", 1.0),
        ("entity:C", "entity:D", 1.0),
    ]
    clusters = detect_communities(edges, max_cluster_size=10, use_lcc=True, seed=1)
    all_entities = {e for c in clusters for e in c.entity_ids}
    assert "entity:C" not in all_entities or "entity:A" not in all_entities
