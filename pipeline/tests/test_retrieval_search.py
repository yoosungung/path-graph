from __future__ import annotations

import json
from unittest.mock import ANY, patch

import pytest

from path_graph.admin.retrieval import api_search_project
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


@patch("path_graph.admin.retrieval.hybrid_search")
@patch("path_graph.admin.retrieval.ProjectStore")
def test_api_search_project(mock_store_cls, mock_hybrid, _project_profile):
    mock_store_cls.return_value.get_project.return_value = _project_profile
    mock_hybrid.return_value = [
        {
            "chunk_id": "c1",
            "text": "hello",
            "rrf_score": 0.03,
        }
    ]

    out = api_search_project("dev", PROJECT_ID, "hello", top_k=5)

    assert out["query"] == "hello"
    assert out["project_id"] == PROJECT_ID
    assert out["project_slug"] == "demo"
    assert len(out["results"]) == 1
    mock_hybrid.assert_called_once_with(
        tenant="dev",
        project_id=PROJECT_ID,
        project_slug="demo",
        query="hello",
        top_k=5,
        settings=ANY,
    )


@patch("path_graph.admin.retrieval.ProjectStore")
def test_api_search_project_not_found(mock_store_cls):
    mock_store_cls.return_value.get_project.return_value = None
    with pytest.raises(ValueError, match="project not found"):
        api_search_project("dev", PROJECT_ID, "q")


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
        "results": [{"chunk_id": "c1", "text": "page body", "rrf_score": 0.02}],
    }
    rc = retrieval_main(
        ["--tenant", "dev", "--project-id", PROJECT_ID, "--query", "wiki"]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "c1" in captured.out
    assert "page body" in captured.out
