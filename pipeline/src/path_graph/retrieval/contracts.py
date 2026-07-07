"""Unified knowledge search request/response contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchMode(str, Enum):
    auto = "auto"
    basic = "basic"
    local = "local"
    global_ = "global"
    drift = "drift"


HitKind = Literal["chunk", "entity", "relationship", "wiki"]


class SearchRequest(BaseModel):
    query: str
    mode: SearchMode = SearchMode.auto
    top_k: int = 10
    include_graph: bool = False
    sub_queries: list[str] = Field(default_factory=list)
    channel_limit: int = 20
    rrf_k: int = 60


class GraphContextBundle(BaseModel):
    entities: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)


class SearchHit(BaseModel):
    kind: HitKind
    id: str
    text: str
    score: float = 0.0
    rrf_score: float | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    mode_resolved: str
    project_id: str
    project_slug: str
    hits: list[SearchHit]
    graph_context: GraphContextBundle | None = None
    sub_queries: list[str] = Field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        """Serialize for Admin API / MCP (includes legacy ``results`` alias)."""
        payload = self.model_dump(mode="json")
        payload["results"] = [h.model_dump(mode="json") for h in self.hits]
        return payload
