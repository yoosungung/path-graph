from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NP = REPO_ROOT / "deploy/k8s/base/networkpolicy.yaml"


def test_pipeline_egress_allows_k8s_api_and_argo():
    text = NP.read_text(encoding="utf-8")
    assert "kubernetes.io/metadata.name: argo" in text
    assert "port: 443" in text
    assert "port: 2746" in text
