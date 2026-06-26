from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST_RAG = REPO_ROOT / "deploy/k8s/base/workflow-templates/pipeline-ingest-rag.yaml"
COLLECT_INGEST = REPO_ROOT / "deploy/k8s/base/workflow-templates/pipeline-collect-ingest-rag.yaml"


def test_pipeline_ingest_rag_parallelism_and_pod_gc():
    text = INGEST_RAG.read_text(encoding="utf-8")
    assert "parallelism: 10" in text
    assert "strategy: OnPodCompletion" in text
    assert "deleteDelayDuration: 60s" in text
    assert "secondsAfterCompletion: 600" in text


def test_pipeline_collect_ingest_rag_pod_gc():
    text = COLLECT_INGEST.read_text(encoding="utf-8")
    assert "parallelism: 10" in text
    assert "strategy: OnPodCompletion" in text
    assert "deleteDelayDuration: 60s" in text
