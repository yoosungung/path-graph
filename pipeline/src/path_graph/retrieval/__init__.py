"""Unified knowledge retrieval (wiki / graph / vector)."""

from path_graph.retrieval.contracts import SearchMode, SearchRequest, SearchResponse
from path_graph.retrieval.unified import knowledge_search

__all__ = [
    "SearchMode",
    "SearchRequest",
    "SearchResponse",
    "knowledge_search",
]
