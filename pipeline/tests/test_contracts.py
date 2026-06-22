import uuid

import pytest

from path_graph.contracts.community import CommunityRecord
from path_graph.contracts.s3_keys import (
    s3_key_chunks,
    s3_key_communities,
    s3_key_graph_context,
    s3_key_raw,
    s3_key_wiki,
)
from path_graph.contracts.schemas import (
    AgentInvokeInput,
    AgentInvokePayload,
    ChunkRecord,
    GraphExtractorInput,
    WikiSynthesizerInput,
)
from path_graph.ids import (
    chunk_id,
    community_id,
    document_id,
    nebula_space_for_chunk,
    nebula_space_name,
    normalize_tenant_slug,
    qdrant_collection_for_chunk,
    qdrant_collection_name,
    tenant_project_index,
    wiki_slug_for_community,
    sha256_text,
)


def test_s3_key_layout():
    t, h = "acme", "abc123"
    assert s3_key_raw(t, "web", h, "f.pdf") == f"raw/{t}/web/{h}/f.pdf"
    doc = str(uuid.uuid4())
    assert s3_key_chunks(t, doc) == f"chunks/{t}/{doc}/chunks.jsonl"


def test_document_id_deterministic():
    a = document_id("t1", "hash1")
    b = document_id("t1", "hash1")
    assert a == b
    assert document_id("t2", "hash1") != a


def test_chunk_id_requires_tenant():
    doc = document_id("t1", "h")
    with pytest.raises(ValueError):
        chunk_id("", doc, 0, "th")


def test_chunk_id_deterministic():
    doc = document_id("t1", "h")
    th = sha256_text("hello")
    assert chunk_id("t1", doc, 0, th) == chunk_id("t1", doc, 0, th)


def test_tenant_slug_and_qdrant_collection():
    slug = normalize_tenant_slug("Acme Corp")
    assert qdrant_collection_name("Acme Corp", 0) == f"path_graph_{slug}_0"
    assert qdrant_collection_name("Acme Corp", 3) == f"path_graph_{slug}_3"


def test_tenant_project_index_is_stable_and_in_range():
    cid = "00000000-0000-0000-0000-000000000011"
    assert tenant_project_index(cid, 4) == tenant_project_index(cid, 4)
    assert 0 <= tenant_project_index(cid, 4) < 4


def test_qdrant_collection_for_chunk():
    cid = "00000000-0000-0000-0000-000000000011"
    project = tenant_project_index(cid, 4)
    assert qdrant_collection_for_chunk("dev", cid, 4) == qdrant_collection_name("dev", project)


def test_nebula_space_for_chunk():
    cid = "00000000-0000-0000-0000-000000000011"
    project = tenant_project_index(cid, 4)
    assert nebula_space_for_chunk("dev", cid, 4) == nebula_space_name("dev", project)
    assert qdrant_collection_for_chunk("dev", cid, 4) == nebula_space_for_chunk("dev", cid, 4)


def test_agent_invoke_payload_requires_tenant():
    with pytest.raises(ValueError):
        AgentInvokePayload.from_input(
            "graph-extractor",
            GraphExtractorInput(
                tenant="",
                project=0,
                batch_id="b1",
                chunks_s3="s3://x",
                idempotency_key="k",
            ),
            "sess",
        )


def test_chunk_record_schema():
    c = ChunkRecord(
        chunk_id="c1",
        document_id="d1",
        tenant="t1",
        chunk_index=0,
        text="hi",
        text_hash="th",
    )
    assert c.tenant == "t1"


def test_project_scoped_s3_keys():
    t, p, b = "acme", 2, "batch-1"
    cid = community_id(t, p, b, 0, "cluster-a")
    assert s3_key_communities(t, p, b) == f"communities/{t}/{p}/{b}/communities.jsonl"
    assert s3_key_graph_context(t, p, b, cid) == f"graph_context/{t}/{p}/{b}/{cid}.json"
    assert s3_key_wiki(t, p, "page-1") == f"wiki/{t}/{p}/page-1.md"


def test_community_id_includes_project():
    a = community_id("t1", 0, "b1", 0, "c1")
    b = community_id("t1", 1, "b1", 0, "c1")
    assert a != b
    assert community_id("t1", 0, "b1", 0, "c1") == a


def test_community_record_build():
    rec = CommunityRecord.build(
        tenant="acme",
        project=2,
        batch_id="batch-1",
        level=0,
        cluster_key="leaf-1",
        entity_ids=["entity:Alice", "entity:Bob"],
    )
    assert rec.project == 2
    assert rec.nebula_space == nebula_space_name("acme", 2)
    assert rec.graph_context_key == s3_key_graph_context(
        "acme", 2, "batch-1", rec.community_id
    )


def test_wiki_slug_for_community():
    cid = community_id("t1", 2, "b1", 0, "c1")
    slug = wiki_slug_for_community(2, 0, cid)
    assert slug.startswith("p2-community-L0-")


def test_graph_extractor_input():
    inp = GraphExtractorInput(
        tenant="dev",
        project=1,
        batch_id="b1",
        chunks_s3="s3://bucket/chunks.jsonl",
        idempotency_key="b1:1",
    )
    payload = AgentInvokePayload.from_input("graph-extractor", inp, "sess")
    assert payload.input["project"] == 1


def test_wiki_synthesizer_input():
    inp = WikiSynthesizerInput(
        tenant="dev",
        project=0,
        community_id="00000000-0000-0000-0000-000000000001",
        community_level=0,
        graph_context_s3="s3://bucket/context.json",
        idempotency_key="b1:0:comm",
    )
    payload = AgentInvokePayload.from_input("wiki-synthesizer", inp, "sess")
    assert payload.input["community_id"] == inp.community_id
