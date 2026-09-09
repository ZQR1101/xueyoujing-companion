"""合同错误体系：错误码与 HTTP 状态对应规格书 §12。"""

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidToken(AppError):
    status_code = 401
    code = "invalid_token"


class MissingIdempotencyKey(AppError):
    status_code = 400
    code = "missing_idempotency_key"


class InvalidRequest(AppError):
    status_code = 422
    code = "invalid_request"


class IllegalState(AppError):
    status_code = 400
    code = "illegal_state"


class InsufficientItems(AppError):
    status_code = 400
    code = "insufficient_items"


class ResourceNotFound(AppError):
    status_code = 404
    code = "resource_not_found"


class VersionConflict(AppError):
    status_code = 409
    code = "version_conflict"


class IdempotencyConflict(AppError):
    status_code = 409
    code = "idempotency_conflict"


class InternalError(AppError):
    status_code = 500
    code = "internal_error"
