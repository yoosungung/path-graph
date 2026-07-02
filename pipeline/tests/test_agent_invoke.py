from unittest.mock import MagicMock, patch

import pytest

from path_graph.contracts.schemas import GraphExtractorInput
from path_graph.steps.agent_invoke import AgentInvokeError, invoke_agent


def test_invoke_agent_unwraps_output_envelope(monkeypatch):
    monkeypatch.setenv("PIPELINE_AGENT_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("PIPELINE_AGENT_INVOKE_MODE", "sync")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    inp = GraphExtractorInput(
        tenant="dev",
        project_id="00000000-0000-0000-0000-000000000001",
        batch_id="b1",
        chunks_s3="s3://bucket/chunks.jsonl",
        idempotency_key="b1:proj",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {
            "entities": [{"id": "entity:A", "name": "A"}],
            "edges": [],
        }
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("path_graph.steps.agent_invoke.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.post.return_value = mock_resp
        result = invoke_agent("graph-extractor", inp, "sess-1")

    assert result["entities"][0]["name"] == "A"
    assert "output" not in result


def test_invoke_agent_raises_without_token(monkeypatch):
    monkeypatch.delenv("PIPELINE_AGENT_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("PIPELINE_AGENT_INVOKE_MODE", "sync")
    from path_graph.config import get_settings

    get_settings.cache_clear()

    inp = GraphExtractorInput(
        tenant="dev",
        project_id="00000000-0000-0000-0000-000000000001",
        batch_id="b1",
        chunks_s3="s3://bucket/chunks.jsonl",
        idempotency_key="b1:proj",
    )
    with pytest.raises(AgentInvokeError, match="PIPELINE_AGENT_ACCESS_TOKEN"):
        invoke_agent("graph-extractor", inp, "sess")
