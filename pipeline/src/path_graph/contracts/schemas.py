from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel, Field


class ChunkRecord(BaseModel):
    chunk_id: str
    document_id: str
    tenant: str
    project_id: str
    chunk_index: int
    text: str
    text_hash: str
    heading_path: list[str] = Field(default_factory=list)
    source_block_type: str | None = None


class BatchManifestLine(BaseModel):
    tenant: str
    project_id: str
    source_id: str
    content_hash: str
    s3_raw_uri: str
    filename: str
    mime: str | None = None


class BatchManifestMeta(BaseModel):
    max_parallel: int = Field(default=10, ge=1, le=100)


class GraphExtractorInput(BaseModel):
    tenant: str
    project_id: str
    batch_id: str
    chunks_s3: str
    output_schema: str = "graph_v1"
    idempotency_key: str


def unwrap_agent_graph_output(body: Any) -> dict[str, Any]:
    """Peel runtime ``{\"output\": ...}`` envelopes until graph_v1 keys are visible."""
    if not isinstance(body, dict):
        return {}
    current: dict[str, Any] = body
    while isinstance(current, dict) and "output" in current:
        if "entities" in current or "edges" in current:
            break
        inner = current.get("output")
        if not isinstance(inner, dict):
            break
        current = inner
    return current


class WikiSynthesizerInput(BaseModel):
    tenant: str
    project_id: str
    project_slug: str
    community_id: str
    community_level: int
    graph_context_s3: str
    output_schema: str = "wiki_v1"
    idempotency_key: str


# Backward-compatible alias
AgentInvokeInput = GraphExtractorInput

AgentInvokeInputUnion = Union[GraphExtractorInput, WikiSynthesizerInput]


class AgentInvokePayload(BaseModel):
    agent: str
    input: dict[str, Any]
    session_id: str

    @classmethod
    def from_input(
        cls,
        agent: str,
        inp: AgentInvokeInputUnion,
        session_id: str,
    ) -> AgentInvokePayload:
        if not inp.tenant:
            raise ValueError("tenant is required")
        return cls(
            agent=agent,
            input=inp.model_dump(),
            session_id=session_id,
        )
