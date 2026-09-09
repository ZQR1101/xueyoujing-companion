"""课程包 → SQLite 导入（幂等 upsert）。

由 scripts/import_curriculum.py 调用；导入前完整校验课程包，
任何核验失败抛 SystemExit 并列出问题。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.infrastructure.curriculum import load_course, validate_course
from app.infrastructure.models import Concept, Question


def import_curriculum(db: Session) -> tuple[int, int]:
    data = load_course()
    errors = validate_course(data)
    if errors:
        print("课程包核验失败：")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    for concept in data.concepts:
        row = db.get(Concept, concept["id"])
        if row is None:
            db.add(
                Concept(
                    id=concept["id"],
                    course_id=data.course_id,
                    title=concept["title"],
                    prerequisite_ids=list(concept["prerequisite_ids"]),
                    resource_ids=list(concept["resource_ids"]),
                )
            )
        else:
            row.title = concept["title"]
            row.prerequisite_ids = list(concept["prerequisite_ids"])
            row.resource_ids = list(concept["resource_ids"])

    for question in data.questions:
        row = db.get(Question, question["id"])
        payload = {
            "id": question["id"],
            "course_id": question["course_id"],
            "primary_concept_id": question["primary_concept_id"],
            "family_id": question["family_id"],
            "type": question["type"],
            "purpose": question["purpose"],
            "prompt": question["prompt"],
            "public_options": list(question["public_options"]),
            "difficulty": question["difficulty"],
            "private_answer": dict(question["private_answer"]),
            "private_hints": list(question["private_hints"]),
            "private_solution": question.get("private_solution"),
            "numeric_config": question.get("numeric_config"),
            "version": question.get("version", 1),
        }
        if row is None:
            db.add(Question(**payload))
        else:
            for key, value in payload.items():
                setattr(row, key, value)

    db.flush()
    return len(data.concepts), len(data.questions)
