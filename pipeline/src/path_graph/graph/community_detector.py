from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import graspologic_native as gn


@dataclass
class HierarchicalCluster:
    level: int
    cluster_key: str
    entity_ids: list[str]
    parent_cluster_key: str | None = None


def _largest_connected_component(
    edges: list[tuple[str, str, float]],
) -> list[tuple[str, str, float]]:
    if not edges:
        return []
    adj: dict[str, set[str]] = {}
    for src, tgt, _ in edges:
        adj.setdefault(src, set()).add(tgt)
        adj.setdefault(tgt, set()).add(src)
    if not adj:
        return edges
    start = next(iter(adj))
    seen = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nbr in adj.get(node, ()):
            if nbr not in seen:
                seen.add(nbr)
                stack.append(nbr)
    return [(s, t, w) for s, t, w in edges if s in seen and t in seen]


def detect_communities(
    edges: list[tuple[str, str, float]],
    *,
    max_cluster_size: int = 10,
    use_lcc: bool = True,
    seed: int = 0xDEADBEEF,
) -> list[HierarchicalCluster]:
    """Run hierarchical Leiden clustering on entity-entity edges."""
    if not edges:
        return []

    working = _largest_connected_component(edges) if use_lcc else list(edges)
    if not working:
        return []

    raw = gn.hierarchical_leiden(
        edges=working,
        max_cluster_size=max_cluster_size,
        seed=seed,
    )

    by_level: dict[int, dict[str, set[str]]] = {}
    parent_map: dict[tuple[int, str], str | None] = {}
    for item in raw:
        level = int(item.level)
        cluster = str(item.cluster)
        node = str(item.node)
        by_level.setdefault(level, {}).setdefault(cluster, set()).add(node)
        parent_map[(level, cluster)] = (
            str(item.parent_cluster) if item.parent_cluster is not None else None
        )

    clusters: list[HierarchicalCluster] = []
    for level in sorted(by_level):
        for cluster_key, entity_ids in sorted(by_level[level].items()):
            parent = parent_map.get((level, cluster_key))
            clusters.append(
                HierarchicalCluster(
                    level=level,
                    cluster_key=cluster_key,
                    entity_ids=sorted(entity_ids),
                    parent_cluster_key=parent,
                )
            )
    return clusters


def clusters_to_community_keys(
    clusters: Iterable[HierarchicalCluster],
) -> dict[tuple[int, str], str]:
    """Map (level, cluster_key) to stable parent community cluster keys."""
    return {(c.level, c.cluster_key): c.cluster_key for c in clusters}
