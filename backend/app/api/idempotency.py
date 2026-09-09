"""幂等写事务模板（§12/A08）。

作用域 = 学生 + 方法 + 规范路径 + 键：
- 同键同载荷：返回首次响应（不再执行业务，绝不重复加证据/建任务）；
- 同键不同载荷：409 idempotency_conflict；
- 幂等记录与业务写入在同一短事务提交，任何异常整体回滚。

事务隔离依赖 database.py 的 BEGIN IMMEDIATE 配方：检查与插入在
同一把 reserved 锁下完成，不存在并发窗口。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import IdempotencyConflict, IllegalState, MissingIdempotencyKey
from app.infrastructure.models import IdempotencyRecord

_ANONYMOUS_SCOPE = "*"

ExecuteFn = Callable[[Session], tuple[Any, int | None, dict | None]]


def _payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_idempotent(
    db: Session,
    *,
    student_id: str,
    request: Request,
    payload: Any,
    execute: ExecuteFn,
) -> dict:
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise MissingIdempotencyKey("写请求必须提供 Idempotency-Key 头")
    if len(key) > 120:
        raise IllegalState("Idempotency-Key 过长（≤120 字符）")

    method = request.method.upper()
    path = request.url.path
    digest = _payload_hash(payload)

    if db.in_transaction():
        db.commit()
    with db.begin():
        record = db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.student_id == student_id,
                IdempotencyRecord.method == method,
                IdempotencyRecord.path == path,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        if record is not None:
            if record.request_hash != digest:
                raise IdempotencyConflict("同键不同载荷，拒绝重放")
            return json.loads(record.response_body)

        data, resource_version, next_action = execute(db)
        body = {
            "data": data,
            "next_action": next_action,
            "resource_version": resource_version,
            "trace_id": getattr(request.state, "trace_id", None),
        }
        db.add(
            IdempotencyRecord(
                student_id=student_id,
                method=method,
                path=path,
                key=key,
                request_hash=digest,
                response_status=200,
                response_body=json.dumps(body, ensure_ascii=False, default=str),
            )
        )
    return body


def run_idempotent_after_external_work(
    db: Session,
    *,
    student_id: str,
    request: Request,
    payload: Any,
    execute: ExecuteFn,
) -> dict:
    """Idempotency for work that waits on an external service.

    The record lookup and final write stay short transactions, while ``execute``
    runs outside a transaction.  This prevents an HTTP model call from holding
    SQLite's global writer lock for its entire duration.
    """
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key:
        raise MissingIdempotencyKey("写请求必须提供 Idempotency-Key 头")
    if len(key) > 120:
        raise IllegalState("Idempotency-Key 过长（≤120 字符）")

    method = request.method.upper()
    path = request.url.path
    digest = _payload_hash(payload)
    if db.in_transaction():
        db.commit()
    with db.begin():
        record = db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.student_id == student_id,
                IdempotencyRecord.method == method,
                IdempotencyRecord.path == path,
                IdempotencyRecord.key == key,
            )
        ).scalar_one_or_none()
        if record is not None:
            if record.request_hash != digest:
                raise IdempotencyConflict("同键不同载荷，拒绝重放")
            return json.loads(record.response_body)

    try:
        data, resource_version, next_action = execute(db)
        body = {
            "data": data,
            "next_action": next_action,
            "resource_version": resource_version,
            "trace_id": getattr(request.state, "trace_id", None),
        }
        db.add(
            IdempotencyRecord(
                student_id=student_id,
                method=method,
                path=path,
                key=key,
                request_hash=digest,
                response_status=200,
                response_body=json.dumps(body, ensure_ascii=False, default=str),
            )
        )
        db.commit()
        return body
    except Exception:
        db.rollback()
        raise


def anonymous_scope(student_id: str | None) -> str:
    return student_id or _ANONYMOUS_SCOPE
