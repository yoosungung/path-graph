from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / "deploy/k8s/base/workflow-templates"
INGEST_RAG = WORKFLOW_DIR / "pipeline-ingest-rag.yaml"
COLLECT_INGEST = WORKFLOW_DIR / "pipeline-collect-ingest-rag.yaml"
DEV_KUSTOMIZATION = REPO_ROOT / "deploy/k8s/overlays/dev/kustomization.yaml"
BUILD_IMAGES_WORKFLOW = REPO_ROOT / ".github/workflows/build-images.yml"
SHA_RE = re.compile(r"^[a-f0-9]{40}$")


def _pipeline_workflow_templates() -> list[Path]:
    return sorted(WORKFLOW_DIR.glob("pipeline-*.yaml"))


def test_pipeline_workflow_images_use_placeholder_not_latest():
    for path in _pipeline_workflow_templates():
        text = path.read_text(encoding="utf-8")
        assert ":latest" not in text, f"{path.name} must not reference :latest"
        assert "path-graph/pipeline:0.0.0" in text, f"{path.name} must use kustomize placeholder tag"


def test_pipeline_workflow_image_pull_policy_if_not_present():
    for path in _pipeline_workflow_templates():
        text = path.read_text(encoding="utf-8")
        assert "imagePullPolicy: Always" not in text, f"{path.name} must not use Always"
        assert "imagePullPolicy: IfNotPresent" in text, f"{path.name} must use IfNotPresent"


def test_dev_kustomization_pins_git_sha_tag():
    text = DEV_KUSTOMIZATION.read_text(encoding="utf-8")
    assert "newTag: latest" not in text
    match = re.search(r"^\s+newTag:\s+(\S+)\s*$", text, re.MULTILINE)
    assert match, "dev overlay must set images.newTag"
    assert SHA_RE.match(match.group(1)), "newTag must be full git SHA"


def test_build_images_workflow_does_not_push_latest():
    text = BUILD_IMAGES_WORKFLOW.read_text(encoding="utf-8")
    assert ":latest" not in text
    assert "github.sha" in text


def test_dev_kustomize_omits_templated_parallelism_for_argo_v4():
    proc = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / "deploy/k8s/overlays/dev")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert 'parallelism: "{{workflow.parameters.max_parallel}}"' not in proc.stdout


def test_dev_kustomize_render_uses_pinned_registry_tag():
    proc = subprocess.run(
        ["kubectl", "kustomize", str(REPO_ROOT / "deploy/k8s/overlays/dev")],
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = proc.stdout
    assert "ghcr.io/yoosungung/path-graph/pipeline:" in rendered
    assert "ghcr.io/yoosungung/path-graph/pipeline:latest" not in rendered
    assert "imagePullPolicy: IfNotPresent" in rendered
    match = re.search(
        r"image:\s+ghcr\.io/yoosungung/path-graph/pipeline:([a-f0-9]{40})",
        rendered,
    )
    assert match, "rendered manifests must pin pipeline image to git SHA"


def test_pipeline_workflow_templates_no_delete_delay_duration():
    """deleteDelayDuration in WorkflowTemplate merges with workflowDefaults → Argo v4.0.6 int64."""
    for path in _pipeline_workflow_templates():
        text = path.read_text(encoding="utf-8")
        assert "deleteDelayDuration:" not in text, f"{path.name} must not declare deleteDelayDuration"


def test_pipeline_ingest_rag_parallelism_pod_gc_and_ttl():
    text = INGEST_RAG.read_text(encoding="utf-8")
    assert 'name: max_parallel' in text
    assert 'parallelism: "{{workflow.parameters.max_parallel}}"' in text
    assert "strategy: OnPodCompletion" in text
    assert "key: ingest-map" in text
    assert "secondsAfterCompletion: 600" in text


def test_pipeline_collect_only_template_exists():
    collect_only = WORKFLOW_DIR / "pipeline-collect.yaml"
    assert collect_only.is_file()
    text = collect_only.read_text(encoding="utf-8")
    assert "collect_source_step" in text
    assert "pipeline-ingest-rag" not in text


def test_pipeline_collect_ingest_rag_parallelism():
    text = COLLECT_INGEST.read_text(encoding="utf-8")
    assert 'name: max_parallel' in text
    assert 'parallelism: "{{workflow.parameters.max_parallel}}"' in text
    assert "strategy: OnPodCompletion" in text
