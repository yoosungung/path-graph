"""Console facade — hybrid RAG + unified knowledge search."""

from path_graph.rag.hybrid_search import hybrid_search
from path_graph.retrieval.unified import knowledge_search

__all__ = ["hybrid_search", "knowledge_search"]
