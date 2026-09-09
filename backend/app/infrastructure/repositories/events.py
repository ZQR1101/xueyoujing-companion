"""事件写入助手（§11 最小事件集合）。

注意：只做写入，不做教学决策；由各服务在短事务内调用。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.enums import EventType
from app.infrastructure.models import Event


def record_event(
    db: Session,
    *,
    student_id: str,
    type: EventType,
    payload: dict[str, Any] | None = None,
    session_id: str | None = None,
    correlation_id: str | None = None,
) -> Event:
    event = Event(
        student_id=student_id,
        session_id=session_id,
        type=type.value,
        payload=payload or {},
        correlation_id=correlation_id,
    )
    db.add(event)
    db.flush()
    return event
