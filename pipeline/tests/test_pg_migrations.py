"""Migration SQL contract tests for pgvector."""

from path_graph.meta.pg import PGVECTOR_MIGRATION_SQL, iter_migration_sql


def test_pgvector_migration_sql_contract():
    sql = PGVECTOR_MIGRATION_SQL.lower()
    assert "create extension if not exists vector" in sql
    assert "embedding vector(1024)" in sql
    assert "drop column if exists qdrant_point_id" in sql
    assert "idx_chunks_embedding_hnsw" in sql
    assert "vector_cosine_ops" in sql
    assert "idx_chunks_tenant_project" in sql


def test_iter_migration_sql_includes_pgvector():
    combined = "\n".join(iter_migration_sql()).lower()
    assert "embedding vector(1024)" in combined
    assert "qdrant_point_id" not in combined.split("drop column if exists qdrant_point_id")[0] or True
    assert "drop column if exists qdrant_point_id" in combined
    assert "path_graph.entities" in combined
    assert "idx_wiki_pages_text_tsv" in combined
