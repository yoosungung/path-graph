"""Heuristic search mode router."""

from __future__ import annotations

import re

from path_graph.retrieval.contracts import SearchMode

_GLOBAL_HINTS = (
    "전체",
    "주요",
    "패턴",
    "비교",
    "요약",
    "overview",
    "summary",
    "themes",
    "overall",
)
_LOCAL_HINTS = re.compile(r"\[\[[^\]]+\]\]")


def resolve_mode(query: str, requested: SearchMode) -> SearchMode:
    if requested != SearchMode.auto:
        return requested

    q = query.strip()
    lowered = q.lower()
    if _LOCAL_HINTS.search(q):
        return SearchMode.local
    if any(hint in lowered for hint in _GLOBAL_HINTS):
        return SearchMode.global_
    tokens = [t for t in re.split(r"\s+", q) if t]
    if len(tokens) <= 4 and any(len(t) >= 2 for t in tokens):
        # short entity-like query
        if any(ord(c) > 127 for c in q) or any(t[0].isupper() for t in tokens if t):
            return SearchMode.local
    if len(tokens) >= 8:
        return SearchMode.drift
    return SearchMode.basic
