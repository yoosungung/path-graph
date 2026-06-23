"""Hera workflow definitions — export to YAML for GitOps."""

from __future__ import annotations

# Optional: run `python -m path_graph.workflows.ingest_rag` after hera installed
# to regenerate deploy/k8s/base/workflow-templates/*.yaml

try:
    from hera.workflows import Container, Workflow, WorkflowTemplate
except ImportError:
    WorkflowTemplate = None  # type: ignore


def build_ingest_rag_template():
    if WorkflowTemplate is None:
        return None
    with WorkflowTemplate(
        name="pipeline-ingest-rag-hera",
        namespace="path-graph",
        entrypoint="ingest-rag",
    ) as wt:
        Container(
            name="ingest-rag",
            image="ghcr.io/yoosungung/path-graph/pipeline:latest",
            command=["python", "-m", "path_graph.steps.ingest_web"],
            args=["--tenant", "{{workflow.parameters.tenant}}", "--rag"],
        )
    return wt
