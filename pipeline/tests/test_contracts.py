import uuid

import pytest

from path_graph.contracts.community import CommunityRecord
from path_graph.contracts.project import KnowledgeBinding, resolve_knowledge_binding
from path_graph.contracts.s3_keys import (
    s3_key_chunks,
    s3_key_communities,
    s3_key_graph_context,
    s3_key_raw,
    s3_key_wiki,
    s3_key_wiki_prefix,
)
from path_graph.contracts.schemas import (
    AgentInvokePayload,
    BatchManifestLine,
    ChunkRecord,
    GraphExtractorInput,
    WikiSynthesizerInput,
)
from path_graph.ids import (
    chunk_id,
    community_id,
    document_id,
    nebula_space_name,
    normalize_tenant_slug,
    qdrant_collection_name,
    wiki_slug_for_community,
    sha256_text,
)

PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def test_s3_key_layout():
    t, h = "acme", "abc123"
    assert (
        s3_key_raw(t, PROJECT_ID, "web", h, "f.pdf")
        == f"raw/{t}/{PROJECT_ID}/web/{h}/f.pdf"
    )
    doc = str(uuid.uuid4())
    assert s3_key_chunks(t, doc) == f"chunks/{t}/{doc}/chunks.jsonl"
    assert s3_key_wiki_prefix(t, PROJECT_ID) == f"wiki/{t}/{PROJECT_ID}/"


def test_document_id_deterministic():
    a = document_id("t1", PROJECT_ID, "hash1")
    b = document_id("t1", PROJECT_ID, "hash1")
    assert a == b
    assert document_id("t2", PROJECT_ID, "hash1") != a
    assert document_id("t1", "660e8400-e29b-41d4-a716-446655440001", "hash1") != a


def test_chunk_id_requires_tenant():
    doc = document_id("t1", PROJECT_ID, "h")
    with pytest.raises(ValueError):
        chunk_id("", doc, 0, "th")


def test_chunk_id_deterministic():
    doc = document_id("t1", PROJECT_ID, "h")
    th = sha256_text("hello")
    assert chunk_id("t1", doc, 0, th) == chunk_id("t1", doc, 0, th)


def test_tenant_slug_and_storage_names():
    slug = normalize_tenant_slug("Acme Corp")
    assert qdrant_collection_name("Acme Corp", "product-docs") == f"path_graph_{slug}_product-docs"
    assert nebula_space_name("Acme Corp", "product-docs") == qdrant_collection_name(
        "Acme Corp", "product-docs"
    )


def test_knowledge_binding_resolve():
    binding = resolve_knowledge_binding("acme", PROJECT_ID, "product-docs")
    assert isinstance(binding, KnowledgeBinding)
    assert binding.rag.qdrant_collection == "path_graph_acme_product-docs"
    assert binding.graph.nebula_space == "path_graph_acme_product-docs"
    assert binding.rag.filter["project_id"] == PROJECT_ID
    assert binding.wiki.s3_prefix == s3_key_wiki_prefix("acme", PROJECT_ID)


def test_agent_invoke_payload_requires_tenant():
    with pytest.raises(ValueError):
        AgentInvokePayload.from_input(
            "graph-extractor",
            GraphExtractorInput(
                tenant="",
                project_id=PROJECT_ID,
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
        project_id=PROJECT_ID,
        chunk_index=0,
        text="hi",
        text_hash="th",
    )
    assert c.tenant == "t1"


def test_batch_manifest_line_requires_project_id():
    line = BatchManifestLine(
        tenant="acme",
        project_id=PROJECT_ID,
        source_id="manual:upload",
        content_hash="abc",
        s3_raw_uri="s3://x",
        filename="a.pdf",
    )
    assert line.project_id == PROJECT_ID


def test_project_scoped_s3_keys():
    t, b = "acme", "batch-1"
    cid = community_id(t, PROJECT_ID, b, 0, "cluster-a")
    assert s3_key_communities(t, PROJECT_ID, b) == f"communities/{t}/{PROJECT_ID}/{b}/communities.jsonl"
    assert s3_key_graph_context(t, PROJECT_ID, b, cid) == (
        f"graph_context/{t}/{PROJECT_ID}/{b}/{cid}.json"
    )
    assert s3_key_wiki(t, PROJECT_ID, "page-1") == f"wiki/{t}/{PROJECT_ID}/page-1.md"


def test_community_id_includes_project():
    a = community_id("t1", PROJECT_ID, "b1", 0, "c1")
    b = community_id("t1", "660e8400-e29b-41d4-a716-446655440001", "b1", 0, "c1")
    assert a != b
    assert community_id("t1", PROJECT_ID, "b1", 0, "c1") == a


def test_community_record_build():
    rec = CommunityRecord.build(
        tenant="acme",
        project_id=PROJECT_ID,
        project_slug="product-docs",
        batch_id="batch-1",
        level=0,
        cluster_key="leaf-1",
        entity_ids=["entity:Alice", "entity:Bob"],
    )
    assert rec.project_id == PROJECT_ID
    assert rec.nebula_space == nebula_space_name("acme", "product-docs")
    assert rec.graph_context_key == s3_key_graph_context(
        "acme", PROJECT_ID, "batch-1", rec.community_id
    )


def test_wiki_slug_for_community():
    cid = community_id("t1", PROJECT_ID, "b1", 0, "c1")
    slug = wiki_slug_for_community("product-docs", 0, cid)
    assert slug.startswith("product-docs-community-L0-")


def test_graph_extractor_input():
    inp = GraphExtractorInput(
        tenant="dev",
        project_id=PROJECT_ID,
        batch_id="b1",
        chunks_s3="s3://bucket/chunks.jsonl",
        idempotency_key="b1:1",
    )
    payload = AgentInvokePayload.from_input("graph-extractor", inp, "sess")
    assert payload.input["project_id"] == PROJECT_ID


def test_wiki_synthesizer_input():
    inp = WikiSynthesizerInput(
        tenant="dev",
        project_id=PROJECT_ID,
        community_id="00000000-0000-0000-0000-000000000001",
        community_level=0,
        graph_context_s3="s3://bucket/context.json",
        idempotency_key="b1:0:comm",
    )
    payload = AgentInvokePayload.from_input("wiki-synthesizer", inp, "sess")
    assert payload.input["community_id"] == inp.community_id
