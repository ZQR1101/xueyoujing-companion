"""掌握度公式 v1 纯函数测试（§7.2 的全部数值示例）。"""

from __future__ import annotations

from app.domain.enums import MasteryStatus
from app.domain.mastery import EvidenceSlice, project


def _slice(i: int, score: int) -> EvidenceSlice:
    return EvidenceSlice(evidence_id=f"e{i}", score=score)


def test_no_evidence_is_unassessed():
    p = project([])
    assert p.estimate is None
    assert p.status is MasteryStatus.unassessed
    assert p.evidence_strength == 0.0


def test_three_correct_is_mastered_08():
    p = project([_slice(1, 1), _slice(2, 1), _slice(3, 1)])
    assert p.estimate == (1 + 3) / (2 + 3)
    assert p.estimate == 0.8
    assert p.status is MasteryStatus.mastered
    assert p.evidence_strength == min(3 / 5, 1)


def test_two_wrong_is_needs_support_025():
    p = project([_slice(1, 0), _slice(2, 0)])
    assert p.estimate == (1 + 0) / (2 + 2)
    assert p.estimate == 0.25
    assert p.status is MasteryStatus.needs_support


def test_one_wrong_then_hint_redo_stays_one_third():
    # 首答错误计分；提示后原题答对不产生证据 → 仍是 n=1、1/3
    p = project([_slice(1, 0)])
    assert p.estimate == (1 + 0) / (2 + 1)
    assert abs(p.estimate - 1 / 3) < 1e-12
    assert p.status is MasteryStatus.developing


def test_boundary_half_is_developing():
    p = project([_slice(1, 1), _slice(2, 0)])
    assert p.estimate == 0.5
    # estimate < 0.5 才 needs_support，0.5 属 developing
    assert p.status is MasteryStatus.developing


def test_two_correct_not_mastered_yet():
    p = project([_slice(1, 1), _slice(2, 1)])
    assert p.estimate == (1 + 2) / (2 + 2)
    assert p.estimate == 0.75
    assert p.status is MasteryStatus.developing


def test_uses_only_latest_eight():
    scores = [_slice(i, 1 if i <= 6 else 0) for i in range(1, 11)]  # 前6对后4错
    p = project(scores)
    # 最近 8 份：第3~10条 → 4 对 4 错 → (1+4)/(2+8)=0.5
    assert p.estimate == (1 + 4) / (2 + 8)
    assert p.evidence_count == 8
    assert p.recent_evidence_ids == [f"e{i}" for i in range(3, 11)]
