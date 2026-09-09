"""轻量课程资源检索（§14 首版）。

返回 source_id、excerpt、relevance_score：
- 本知识点资源直接命中 1.0；
- 前置知识点资源 0.6；
- 若带 query，按字符重叠比例调整排序（纯确定性，不调用模型）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.infrastructure.curriculum import CourseData

_PREREQUISITE_RELEVANCE = 0.6
_EXCERPT_CHARS = 160


@dataclass(frozen=True)
class RetrievalResult:
    source_id: str
    concept_id: str
    title: str
    excerpt: str
    relevance_score: float


def _query_score(text: str, query: str) -> float:
    if not query:
        return 1.0
    chars = {c for c in query if not c.isspace()}
    if not chars:
        return 1.0
    overlap = len(chars & set(text)) / len(chars)
    return max(0.1, min(1.0, overlap))


def _excerpt(content: str) -> str:
    collapsed = " ".join(content.split())
    return collapsed[:_EXCERPT_CHARS]


def retrieve_for_concept(
    data: CourseData, concept_id: str, query: str = "", top_k: int = 3
) -> list[RetrievalResult]:
    concept = data.concept(concept_id)
    if concept is None:
        return []

    resources_by_id = {r["id"]: r for r in data.resources}
    candidates: list[tuple[str, str, str, float]] = []

    for rid in concept["resource_ids"]:
        if rid in resources_by_id:
            candidates.append((rid, concept_id, resources_by_id[rid]["title"], 1.0))
    for pre_id in concept["prerequisite_ids"]:
        pre = data.concept(pre_id)
        if pre is None:
            continue
        for rid in pre["resource_ids"]:
            if rid in resources_by_id:
                candidates.append(
                    (rid, pre_id, resources_by_id[rid]["title"], _PREREQUISITE_RELEVANCE)
                )

    results: list[RetrievalResult] = []
    for rid, owner_id, title, base_score in candidates:
        content = data.read_resource(rid)
        results.append(
            RetrievalResult(
                source_id=rid,
                concept_id=owner_id,
                title=title,
                excerpt=_excerpt(content),
                relevance_score=base_score,
            )
        )

    scored = [
        replace(
            r,
            relevance_score=round(
                r.relevance_score * _query_score(r.title + r.excerpt, query), 4
            ),
        )
        for r in results
    ]
    scored.sort(key=lambda r: (-r.relevance_score, r.source_id))
    return scored[:top_k]
