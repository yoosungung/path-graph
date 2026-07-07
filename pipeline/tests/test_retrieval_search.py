from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from path_graph.admin.retrieval import api_search_project
from path_graph.config import Settings
from path_graph.steps.retrieval_search import main as retrieval_main

from constants import PROJECT_ID


@pytest.fixture
def _project_profile():
    from path_graph.contracts.project import ProjectProfile
    from datetime import UTC, datetime

    return ProjectProfile(
        tenant="dev",
        id=PROJECT_ID,
        slug="demo",
        name="Demo",
        created_at=datetime.now(UTC),
    )


@patch("path_graph.admin.retrieval.knowledge_search")
@patch("path_graph.admin.retrieval.ProjectStore")
def test_api_search_project(mock_store_cls, mock_search, _project_profile):
    mock_store_cls.return_value.get_project.return_value = _project_profile
    from path_graph.retrieval.contracts import SearchHit, SearchResponse

    mock_search.return_value = SearchResponse(
        query="hello",
        mode_resolved="basic",
        project_id=PROJECT_ID,
        project_slug="demo",
        hits=[
            SearchHit(
                kind="chunk",
                id="c1",
                text="hello",
                rrf_score=0.03,
                provenance={"chunk_id": "c1"},
            )
        ],
    )

    out = api_search_project(
        "dev",
        PROJECT_ID,
        "hello",
        top_k=5,
        mode="basic",
        settings=Settings(path_graph_dsn="postgresql://localhost/test"),
    )

    assert out["query"] == "hello"
    assert out["project_id"] == PROJECT_ID
    assert out["project_slug"] == "demo"
    assert out["mode_resolved"] == "basic"
    assert len(out["hits"]) == 1
    assert len(out["results"]) == 1
    mock_search.assert_called_once()


@patch("path_graph.admin.retrieval.ProjectStore")
def test_api_search_project_not_found(mock_store_cls):
    mock_store_cls.return_value.get_project.return_value = None
    with pytest.raises(ValueError, match="project not found"):
        api_search_project(
            "dev",
            PROJECT_ID,
            "q",
            settings=Settings(path_graph_dsn="postgresql://localhost/test"),
        )


@patch("path_graph.steps.retrieval_search.api_search_project")
def test_retrieval_search_cli_json(mock_api):
    mock_api.return_value = {
        "query": "test",
        "project_id": PROJECT_ID,
        "project_slug": "demo",
        "results": [],
    }
    rc = retrieval_main(
        [
            "--tenant",
            "dev",
            "--project-id",
            PROJECT_ID,
            "--query",
            "test",
            "--json",
        ]
    )
    assert rc == 0
    mock_api.assert_called_once()


@patch("path_graph.steps.retrieval_search.api_search_project")
def test_retrieval_search_cli_prints_hits(mock_api, capsys):
    mock_api.return_value = {
        "query": "wiki",
        "project_id": PROJECT_ID,
        "project_slug": "demo",
        "mode_resolved": "basic",
        "hits": [{"id": "c1", "kind": "chunk", "text": "page body", "rrf_score": 0.02}],
        "results": [{"id": "c1", "kind": "chunk", "text": "page body", "rrf_score": 0.02}],
    }
    rc = retrieval_main(
        ["--tenant", "dev", "--project-id", PROJECT_ID, "--query", "wiki"]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "c1" in captured.out
    assert "page body" in captured.out
