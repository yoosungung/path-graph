from path_graph.rag.rrf import reciprocal_rank_fusion


def test_reciprocal_rank_fusion_merges_overlapping_ids():
    merged = reciprocal_rank_fusion(
        [
            [{"id": "a", "text": "a"}, {"id": "b", "text": "b"}],
            [{"id": "b", "text": "b2"}, {"id": "c", "text": "c"}],
        ],
        top_n=3,
    )
    ids = [row["id"] for row in merged]
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}
    assert merged[0]["rrf_score"] > merged[1]["rrf_score"]
