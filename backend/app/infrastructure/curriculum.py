"""课程包加载与核验（§8）。

课程包目录默认 curriculum/quadratic（相对仓库根）。加载后做完整校验：
依赖图无环、题目引用有效、每知识点 ≥4 个题族、答案可被评分器自检通过。
任何核验失败都会抛 ValueError 并列出全部问题（课程作者须修复后重试）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.domain import scoring
from app.domain.enums import QuestionPurpose, QuestionType
from app.domain.graph import topo_depth, topo_sort, validate_acyclic

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_COURSE_DIR = _PROJECT_ROOT / "curriculum" / "quadratic"

MAX_HINTS = 4
MIN_FAMILIES_PER_CONCEPT = 4


@dataclass(frozen=True)
class CourseData:
    course_id: str
    title: str
    concepts: tuple[dict, ...]
    questions: tuple[dict, ...]
    resources: tuple[dict, ...]
    course_dir: Path = _DEFAULT_COURSE_DIR
    topo_order: list[str] = field(default_factory=list)
    depth_by_concept: dict[str, int] = field(default_factory=dict)

    @property
    def prerequisites(self) -> dict[str, list[str]]:
        return {c["id"]: list(c["prerequisite_ids"]) for c in self.concepts}

    def concept(self, concept_id: str) -> dict | None:
        return next((c for c in self.concepts if c["id"] == concept_id), None)

    def questions_for_concept(self, concept_id: str) -> list[dict]:
        return [q for q in self.questions if q["primary_concept_id"] == concept_id]

    def read_resource(self, resource_id: str) -> str:
        resource = next((r for r in self.resources if r["id"] == resource_id), None)
        if resource is None:
            return ""
        path = self.course_dir / resource["path"]
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""


def _load_json(path: Path) -> dict | list:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_course(course_dir: Path | None = None) -> CourseData:
    directory = course_dir or _DEFAULT_COURSE_DIR
    course = _load_json(directory / "course.json")
    questions = _load_json(directory / "questions.json")

    data = CourseData(
        course_id=course["course_id"],
        title=course["title"],
        concepts=tuple(course["concepts"]),
        questions=tuple(questions),
        resources=tuple(course.get("resources", [])),
        course_dir=directory,
    )
    data.topo_order[:] = topo_sort(data.prerequisites)
    data.depth_by_concept.update(topo_depth(data.prerequisites))
    return data


def validate_course(data: CourseData, course_dir: Path | None = None) -> list[str]:
    errors: list[str] = []
    concept_ids = {c["id"] for c in data.concepts}
    resource_ids = {r["id"] for r in data.resources}

    try:
        validate_acyclic(data.prerequisites)
    except ValueError as exc:
        errors.append(str(exc))

    for concept in data.concepts:
        unknown_pre = set(concept["prerequisite_ids"]) - concept_ids
        if unknown_pre:
            errors.append(f"{concept['id']} 的前置不存在：{sorted(unknown_pre)}")
        unknown_res = set(concept["resource_ids"]) - resource_ids
        if unknown_res:
            errors.append(f"{concept['id']} 的资源不存在：{sorted(unknown_res)}")

    directory = course_dir or _DEFAULT_COURSE_DIR
    for resource in data.resources:
        path = directory / resource["path"]
        if not path.exists():
            errors.append(f"资源文件缺失：{resource['path']}")

    families_by_concept: dict[str, set[str]] = {cid: set() for cid in concept_ids}
    seen_question_ids: set[str] = set()
    for question in data.questions:
        qid = question["id"]
        if qid in seen_question_ids:
            errors.append(f"题目 id 重复：{qid}")
        seen_question_ids.add(qid)

        if question["course_id"] != data.course_id:
            errors.append(f"{qid} course_id 不属于本课程")
        if question["primary_concept_id"] not in concept_ids:
            errors.append(f"{qid} 引用了未知知识点 {question['primary_concept_id']}")
            continue
        families_by_concept[question["primary_concept_id"]].add(question["family_id"])

        try:
            QuestionType(question["type"])
        except ValueError:
            errors.append(f"{qid} 题型非法：{question['type']}")
        try:
            QuestionPurpose(question["purpose"])
        except ValueError:
            errors.append(f"{qid} 用途非法：{question['purpose']}")

        if question["type"] == QuestionType.mcq.value:
            options = question["public_options"]
            keys = [o["key"] for o in options]
            if len(keys) < 2 or len(set(keys)) != len(keys):
                errors.append(f"{qid} 选项键非法：{keys}")
            if question["private_answer"]["kind"] != "option":
                errors.append(f"{qid} 选择题答案 kind 应为 option")
            elif question["private_answer"]["value"] not in keys:
                errors.append(f"{qid} 答案键不在选项中：{question['private_answer']['value']}")
        else:
            if question["private_answer"]["kind"] != "numeric":
                errors.append(f"{qid} 数值题答案 kind 应为 numeric")
            if not question.get("numeric_config"):
                errors.append(f"{qid} 缺少 numeric_config")

        hints = question.get("private_hints", [])
        if not (1 <= len(hints) <= MAX_HINTS):
            errors.append(f"{qid} 提示数量应为 1~{MAX_HINTS}：实际 {len(hints)}")

        solution = question.get("private_solution")
        if not isinstance(solution, str) or not solution.strip():
            errors.append(f"{qid} 缺少 private_solution（合同 v1.2 R6）")
        elif solution in hints:
            errors.append(f"{qid} private_solution 不得与任一提示相同")

        # 答案自检：评分器必须能判对核验过的标准答案
        try:
            result = scoring.grade_question(question, str(question["private_answer"]["value"]))
            if not result.correct:
                errors.append(f"{qid} 答案自检失败：标准答案被判为错误")
        except scoring.AnswerFormatError as exc:
            errors.append(f"{qid} 答案自检无法解析：{exc}")

    for cid, families in families_by_concept.items():
        if len(families) < MIN_FAMILIES_PER_CONCEPT:
            errors.append(f"{cid} 题族不足 {MIN_FAMILIES_PER_CONCEPT} 个：实际 {len(families)}")

    return errors


@lru_cache
def get_course_data() -> CourseData:
    data = load_course()
    errors = validate_course(data)
    if errors:
        raise ValueError("课程包核验失败：\n- " + "\n- ".join(errors))
    return data
