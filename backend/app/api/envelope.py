"""统一响应信封（规格书 §12）：{"data", "next_action", "resource_version", "trace_id"}。"""

from __future__ import annotations

from typing import Any

from fastapi import Request


def envelope(
    request: Request,
    data: Any,
    *,
    resource_version: int | None = None,
    next_action: dict | None = None,
) -> dict:
    return {
        "data": data,
        "next_action": next_action,
        "resource_version": resource_version,
        "trace_id": getattr(request.state, "trace_id", None),
    }
