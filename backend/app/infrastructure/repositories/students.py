"""学生仓库：查询与归属检查。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.models import Student


def get_by_token_hash(db: Session, token_hash: str) -> Student | None:
    return db.execute(
        select(Student).where(Student.token_hash == token_hash)
    ).scalar_one_or_none()


def add(db: Session, student: Student) -> Student:
    db.add(student)
    db.flush()
    return student


def update_daily_minutes(db: Session, student: Student, daily_minutes: int) -> None:
    student.daily_minutes = daily_minutes
    db.flush()
