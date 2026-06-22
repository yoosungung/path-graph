from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel, Field


class ChunkRecord(BaseModel):
    chunk_id: str
    document_id: str
    tenant: str
    chunk_index: int
    text: str
    text_hash: str
    heading_path: list[str] = Field(default_factory=list)
    source_block_type: str | None = None


class BatchManifestLine(BaseModel):
    tenant: str
    source_id: str
    content_hash: str
    s3_raw_uri: str
    filename: str
    mime: str | None = None


class GraphExtractorInput(BaseModel):
    tenant: str
    project: int
    batch_id: str
    chunks_s3: str
    output_schema: str = "graph_v1"
    idempotency_key: str


class WikiSynthesizerInput(BaseModel):
    tenant: str
    project: int
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
