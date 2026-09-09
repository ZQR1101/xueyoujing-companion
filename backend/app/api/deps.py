"""请求级依赖：数据库会话与演示令牌鉴权。

学生身份只来自服务端签发的演示令牌；接口不接受任意 student_id（§6）。
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Iterator

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import InvalidToken
from app.infrastructure.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.models import Student

DbSession = Annotated[Session, Depends(get_db)]


def hash_token(token: str) -> str:
    pepper = get_settings().demo_token_secret
    return hashlib.sha256(f"{pepper}:{token}".encode("utf-8")).hexdigest()


def get_student(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Student:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    if not token:
        raise InvalidToken("缺少演示令牌，请先调用 POST /api/v1/demo-identities")
    student = db.execute(
        select(Student).where(Student.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if student is None:
        raise InvalidToken("演示令牌无效")
    return student


CurrentStudent = Annotated[Student, Depends(get_student)]
