"""Tests for async agent job invoke (submit + poll)."""

from unittest.mock import MagicMock, patch

import pytest

from path_graph.contracts.schemas import GraphExtractorInput
from path_graph.steps.agent_invoke import AgentInvokeError, invoke_agent


def _graph_input() -> GraphExtractorInput:
    return GraphExtractorInput(
        tenant="dev",
        project_id="00000000-0000-0000-0000-000000000001",
        batch_id="b1",
        chunks_s3="s3://bucket/chunks.jsonl",
        idempotency_key="b1:proj",
    )


def test_invoke_agent_async_poll_unwraps_output(monkeypatch):
    monkeypatch.setenv("PIPELINE_AGENT_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("PIPELINE_AGENT_INVOKE_MODE", "async_poll")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    submit_resp = MagicMock()
    submit_resp.status_code = 202
    submit_resp.json.return_value = {"job_id": "job-1", "status": "pending"}
    submit_resp.raise_for_status = MagicMock()

    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {
        "job_id": "job-1",
        "status": "succeeded",
        "output": {"entities": [{"id": "entity:A", "name": "A"}], "edges": []},
    }
    poll_resp.raise_for_status = MagicMock()

    with patch("path_graph.steps.agent_invoke.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = submit_resp
        client.get.return_value = poll_resp
        result = invoke_agent("graph-extractor", _graph_input(), "sess-1")

    assert result["entities"][0]["name"] == "A"
    client.post.assert_called_once()
    assert "/v1/agents/jobs" in client.post.call_args.args[0]
    client.get.assert_called_once()
    assert "job-1" in client.get.call_args.args[0]


def test_invoke_agent_async_poll_unwraps_runtime_output_envelope(monkeypatch):
    monkeypatch.setenv("PIPELINE_AGENT_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("PIPELINE_AGENT_INVOKE_MODE", "async_poll")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    graph_v1 = {
        "entities": [{"id": "entity:프로젝트", "name": "프로젝트"}],
        "edges": [],
    }
    submit_resp = MagicMock()
    submit_resp.status_code = 202
    submit_resp.json.return_value = {"job_id": "job-2", "status": "pending"}
    submit_resp.raise_for_status = MagicMock()

    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {
        "job_id": "job-2",
        "status": "succeeded",
        "output": {
            "output": {
                "tenant": "didim",
                "entities": graph_v1["entities"],
                "edges": graph_v1["edges"],
            }
        },
    }
    poll_resp.raise_for_status = MagicMock()

    with patch("path_graph.steps.agent_invoke.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = submit_resp
        client.get.return_value = poll_resp
        result = invoke_agent("graph-extractor", _graph_input(), "sess-1")

    assert result["entities"][0]["name"] == "프로젝트"


def test_invoke_agent_async_poll_times_out(monkeypatch):
    monkeypatch.setenv("PIPELINE_AGENT_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("PIPELINE_AGENT_INVOKE_MODE", "async_poll")
    monkeypatch.setenv("PIPELINE_AGENT_JOB_MAX_WAIT_S", "0")
    monkeypatch.setenv("PIPELINE_AGENT_JOB_POLL_INTERVAL_S", "0")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    submit_resp = MagicMock()
    submit_resp.status_code = 202
    submit_resp.json.return_value = {"job_id": "job-1", "status": "pending"}
    submit_resp.raise_for_status = MagicMock()

    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {"job_id": "job-1", "status": "running"}
    poll_resp.raise_for_status = MagicMock()

    with patch("path_graph.steps.agent_invoke.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value = submit_resp
        client.get.return_value = poll_resp
        with pytest.raises(AgentInvokeError, match="timed out"):
            invoke_agent("graph-extractor", _graph_input(), "sess")
