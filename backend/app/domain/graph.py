"""课程知识图：无环校验与稳定拓扑排序（§8）。"""

from __future__ import annotations

from collections import defaultdict


def validate_acyclic(prerequisites: dict[str, list[str]]) -> None:
    """prerequisites: {concept_id: [前置 concept_id]}；有环抛 ValueError。"""
    remaining = {cid: set(prereqs) for cid, prereqs in prerequisites.items()}
    resolved: set[str] = set()
    while remaining:
        ready = sorted(cid for cid, prereqs in remaining.items() if prereqs <= resolved)
        if not ready:
            cycle = sorted(remaining)
            raise ValueError(f"课程依赖图存在环：{cycle}")
        resolved.update(ready)
        for cid in ready:
            del remaining[cid]


def topo_sort(prerequisites: dict[str, list[str]]) -> list[str]:
    """稳定拓扑序：同一层按 concept_id 字典序，保证结果可复现。"""
    validate_acyclic(prerequisites)
    dependents: dict[str, list[str]] = defaultdict(list)
    indegree = {cid: 0 for cid in prerequisites}
    for cid, prereqs in prerequisites.items():
        indegree[cid] = len(prereqs)
        for pre in prereqs:
            dependents[pre].append(cid)

    queue = sorted(cid for cid, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for nxt in dependents[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
                queue.sort()
    return ordered


def topo_depth(prerequisites: dict[str, list[str]]) -> dict[str, int]:
    """每个节点的拓扑深度（同层排序用）。"""
    depth: dict[str, int] = {}
    for cid in topo_sort(prerequisites):
        prereqs = prerequisites[cid]
        depth[cid] = max((depth[p] for p in prereqs), default=-1) + 1
    return depth
