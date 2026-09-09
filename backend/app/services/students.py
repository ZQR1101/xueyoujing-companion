"""演示学生服务。"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.api.deps import hash_token
from app.infrastructure.models import Student
from app.infrastructure.repositories import students as students_repo

DEFAULT_DAILY_MINUTES = 30


def create_demo_student(db: Session, display_name: str) -> tuple[Student, str]:
    token = secrets.token_urlsafe(24)
    student = Student(
        display_name=display_name.strip(),
        daily_minutes=DEFAULT_DAILY_MINUTES,
        token_hash=hash_token(token),
    )
    students_repo.add(db, student)
    return student, token
