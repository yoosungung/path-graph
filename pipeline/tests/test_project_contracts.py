import pytest

from path_graph.contracts.project import ProjectCreate, resolve_knowledge_binding
from path_graph.ids import qdrant_collection_name


PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def test_resolve_knowledge_binding_collection_matches_slug():
    binding = resolve_knowledge_binding("dev", PROJECT_ID, "my-project")
    expected = qdrant_collection_name("dev", "my-project")
    assert binding.rag.qdrant_collection == expected
    assert binding.graph.nebula_space == expected


def test_project_create_slug_optional():
    body = ProjectCreate(name="Product Docs")
    assert body.slug is None
