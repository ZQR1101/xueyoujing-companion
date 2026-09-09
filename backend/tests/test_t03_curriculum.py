"""T03 课程与评分验收测试。

覆盖：DAG 无环、题族数量、答案自检、确定性评分（选择题/数值规范化/禁 eval）、
公开 DTO 无答案泄露、导入幂等。
"""

from __future__ import annotations

import pytest

from app.api.serializers import public_question_dto
from app.domain import scoring
from app.domain.graph import topo_sort, validate_acyclic
from app.infrastructure.curriculum import load_course, validate_course
from app.infrastructure.curriculum_import import import_curriculum
from app.infrastructure.models import Question


@pytest.fixture(scope="module")
def course():
    return load_course()


def test_course_loads_and_validates(course):
    errors = validate_course(course)
    assert errors == []
    assert course.course_id == "quadratic"
    assert len(course.concepts) == 6
    assert len(course.questions) == 300


def test_dag_acyclic_and_stable_topo(course):
    validate_acyclic(course.prerequisites)
    ordered = topo_sort(course.prerequisites)
    assert ordered[0] == "C01"
    assert ordered[-1] == "C06"
    assert course.depth_by_concept["C04"] == course.depth_by_concept["C05"]


def test_cycle_detection():
    cyclic = {"A": ["C"], "B": ["A"], "C": ["B"]}
    with pytest.raises(ValueError, match="环"):
        validate_acyclic(cyclic)


def test_four_families_per_concept(course):
    for concept in course.concepts:
        families = {
            q["family_id"]
            for q in course.questions_for_concept(concept["id"])
        }
        assert len(families) >= 4, concept["id"]
    purposes = {q["purpose"] for q in course.questions}
    assert purposes == {"screening", "practice", "transfer", "review"}


def test_mcq_grading():
    question = {
        "type": "mcq",
        "public_options": [
            {"key": "A", "text": "-9"},
            {"key": "B", "text": "9"},
        ],
        "private_answer": {"kind": "option", "value": "B"},
    }
    assert scoring.grade_question(question, "B").correct
    assert scoring.grade_question(question, " b ").correct
    assert not scoring.grade_question(question, "A").correct
    with pytest.raises(scoring.AnswerFormatError):
        scoring.grade_question(question, "E")


def test_numeric_integer_grading():
    question = {
        "type": "numeric",
        "private_answer": {"kind": "numeric", "value": "25"},
        "numeric_config": {"kind": "integer"},
    }
    assert scoring.grade_question(question, "25").correct
    assert scoring.grade_question(question, " 25 ").correct
    assert scoring.grade_question(question, "+25").correct
    assert not scoring.grade_question(question, "-25").correct
    # 整数题收到小数 = 配置外格式 → AnswerFormatError（API 层转 422）
    with pytest.raises(scoring.AnswerFormatError):
        scoring.grade_question(question, "25.5")


def test_numeric_decimal_tolerance():
    question = {
        "type": "numeric",
        "private_answer": {"kind": "numeric", "value": "4.25"},
        "numeric_config": {"kind": "decimal", "tolerance": 0.001},
    }
    assert scoring.grade_question(question, "4.25").correct
    assert scoring.grade_question(question, "4.2505").correct
    assert not scoring.grade_question(question, "4.3").correct


def test_numeric_rational_equivalence():
    question = {
        "type": "numeric",
        "private_answer": {"kind": "numeric", "value": "1/4"},
        "numeric_config": {"kind": "rational"},
    }
    assert scoring.grade_question(question, "1/4").correct
    assert scoring.grade_question(question, "2/8").correct  # 约分等价
    assert scoring.grade_question(question, "0.25").correct
    assert scoring.grade_question(question, "-1/4").correct is False
    with pytest.raises(scoring.AnswerFormatError):
        scoring.grade_question(question, "1/0")


def test_no_eval_execution():
    question = {
        "type": "numeric",
        "private_answer": {"kind": "numeric", "value": "2"},
        "numeric_config": {"kind": "integer"},
    }
    for malicious in ["__import__('os').system('echo hi')", "1+1", "20-5*2", "os.getcwd()"]:
        with pytest.raises(scoring.AnswerFormatError):
            scoring.grade_question(question, malicious)


def test_all_answered_questions_self_verify(course):
    for question in course.questions:
        result = scoring.grade_question(
            question, str(question["private_answer"]["value"])
        )
        assert result.correct, question["id"]


def test_hints_do_not_reveal_answers(course):
    """合同 v1.1：提示不得泄露完整答案。

    自动化覆盖可靠场景：选择题的「选 X」表述；小数/分数答案的值泄露。
    整数答案的泄露检查依赖人工抽检（单字符子串误报率高），见 docs/题库抽检记录.md。
    """
    for question in course.questions:
        hints = question["private_hints"]
        if question["type"] == "mcq":
            key = question["private_answer"]["value"]
            for hint in hints:
                assert f"选 {key}" not in hint, question["id"]
        else:
            value = str(question["private_answer"]["value"])
            if ("." in value) or ("/" in value):
                for hint in hints:
                    assert value not in hint, question["id"]


def test_public_question_dto_hides_private_fields(db_factory, course):
    session = db_factory()
    with session.begin():
        assert import_curriculum(session) == (6, 300)

    question = session.get(Question, "Q-C01-F1")
    dto = public_question_dto(question)
    forbidden = {"private_answer", "private_hints", "numeric_config", "answer", "hints"}
    assert forbidden.isdisjoint(dto.keys())
    assert dto["public_options"] == question.public_options
    # 序列化后的 JSON 也不含答案
    import json

    assert "answer" not in json.dumps(dto, ensure_ascii=False).lower().replace(
        "public_options", ""
    )


def test_import_is_idempotent(db_factory):
    session = db_factory()
    with session.begin():
        import_curriculum(session)
    from app.infrastructure.models import Concept

    with session.begin():
        import_curriculum(session)
        assert len(list(session.query(Question).all())) == 300
        assert len(list(session.query(Concept).all())) == 6
