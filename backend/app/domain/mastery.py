"""掌握度策略 v1（§7.2 唯一权威实现，禁止在其他层改动公式）。

可重复计算：
    n = 有效证据数（最近最多 8 份不同 family）
    estimate = null                    当 n = 0
    estimate = (1 + sum(scores)) / (2 + n)
    evidence_strength = min(n / 5, 1)

状态判定（按顺序）：
    1. n=0                                -> unassessed
    2. n>=3 且 estimate>=0.8 且最近两份均正确 -> mastered
    3. n>=2 且 estimate<0.5               -> needs_support
    4. 其他                               -> developing
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import MasteryStatus

FORMULA_VERSION = "v1"
MAX_EVIDENCE = 8
STRENGTH_TARGET = 5
MASTERED_MIN_EVIDENCE = 3
MASTERED_ESTIMATE = 0.8
NEEDS_SUPPORT_MIN_EVIDENCE = 2
NEEDS_SUPPORT_ESTIMATE = 0.5


@dataclass(frozen=True)
class EvidenceSlice:
    """一条有效证据：evidence_id + score(0/1)。顺序：旧 → 新。"""

    evidence_id: str
    score: int


@dataclass(frozen=True)
class MasteryProjection:
    estimate: float | None
    evidence_count: int
    evidence_strength: float
    status: MasteryStatus
    recent_evidence_ids: list[str]


def project(evidences: list[EvidenceSlice]) -> MasteryProjection:
    """evidences 必须按创建时间升序、已按 family 去重。"""
    recent = evidences[-MAX_EVIDENCE:]
    n = len(recent)
    if n == 0:
        return MasteryProjection(
            estimate=None,
            evidence_count=0,
            evidence_strength=0.0,
            status=MasteryStatus.unassessed,
            recent_evidence_ids=[],
        )

    total = sum(e.score for e in recent)
    estimate = (1 + total) / (2 + n)
    strength = min(n / STRENGTH_TARGET, 1)
    last_two = [e.score for e in recent[-2:]]

    if (
        n >= MASTERED_MIN_EVIDENCE
        and estimate >= MASTERED_ESTIMATE
        and last_two == [1, 1]
    ):
        status = MasteryStatus.mastered
    elif n >= NEEDS_SUPPORT_MIN_EVIDENCE and estimate < NEEDS_SUPPORT_ESTIMATE:
        status = MasteryStatus.needs_support
    else:
        status = MasteryStatus.developing

    return MasteryProjection(
        estimate=estimate,
        evidence_count=n,
        evidence_strength=strength,
        status=status,
        recent_evidence_ids=[e.evidence_id for e in recent],
    )


def projection_dto(projection: MasteryProjection) -> dict:
    return {
        "estimate": projection.estimate,
        "evidence_count": projection.evidence_count,
        "evidence_strength": projection.evidence_strength,
        "status": projection.status.value,
    }
