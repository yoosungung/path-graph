import pytest

from path_graph.contracts.project import (
    ProjectCreate,
    resolve_knowledge_binding,
    slug_from_name,
    wiki_vfs_mount_path,
)
from path_graph.ids import index_namespace


PROJECT_ID = "550e8400-e29b-41d4-a716-446655440000"


def test_resolve_knowledge_binding_collection_matches_slug():
    binding = resolve_knowledge_binding("dev", PROJECT_ID, "my-project")
    expected = index_namespace("dev", "my-project")
    assert binding.rag.index_namespace == expected
    assert binding.graph.nebula_space == expected


def test_project_create_slug_optional():
    body = ProjectCreate(name="Product Docs")
    assert body.slug is None


def test_slug_from_name_latin():
    assert slug_from_name("Product Docs") == "product_docs"


def test_slug_from_name_non_latin_fallback():
    slug = slug_from_name("문서 프로젝트")
    assert slug.startswith("p_")
    assert len(slug) == 10
    assert slug_from_name("문서 프로젝트") == slug


def test_wiki_vfs_mount_path_uses_project_name():
    assert wiki_vfs_mount_path("회사규정", "p_1dbc0db0") == "/wiki/회사규정/"
    assert wiki_vfs_mount_path("Product Docs", "product_docs") == "/wiki/Product Docs/"


def test_resolve_knowledge_binding_wiki_mount_from_name():
    binding = resolve_knowledge_binding(
        "dev", PROJECT_ID, "p_1dbc0db0", project_name="회사규정"
    )
    assert binding.wiki.vfs_mount == "/wiki/회사규정/"
