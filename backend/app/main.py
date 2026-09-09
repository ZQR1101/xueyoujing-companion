"""FastAPI 入口。

- /healthz：基础设施探活（合同外端点）。
- /api/v1/*：业务接口（规格书 §12）。
- 错误统一为 {"error": {"code", "message"}, "trace_id"}。
"""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import agent, assessments, demo, diagnosis_report, exercises, goals, me, motivation, path_decision, reflection, sessions, tasks, tutoring_agent, tutoring_rag
from app.domain.errors import AppError
from app.infrastructure.config import get_settings
from app.infrastructure.curriculum import get_course_data
from app.infrastructure.llm.gateway import runtime_status
from app.infrastructure.rag_index import get_rag_index

logger = logging.getLogger("xueyoujing")


def _error_body(request: Request, code: str, message: str) -> dict:
    return {
        "error": {"code": code, "message": message},
        "trace_id": getattr(request.state, "trace_id", None),
    }


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="学有所径 API",
        version="0.2.0",
        description="自适应伴学智能体（独立项目）。当前交付：T02 数据与事务骨架。",
    )
    app.add_middleware(
        CORSMiddleware,
        # 本地开发时 Vite 可能使用 5173/5174，且 localhost 与 127.0.0.1
        # 会被浏览器视为不同 Origin；统一允许本机前端来源，避免假性“无法连接后端”。
        allow_origins=sorted({settings.frontend_dev_url, "http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"}),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_trace_id(request: Request, call_next):  # noqa: ANN202
        request.state.trace_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body(request, "invalid_request", "输入格式错误"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        codes = {404: "resource_not_found", 405: "method_not_allowed"}
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(
                request,
                codes.get(exc.status_code, "http_error"),
                str(exc.detail),
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_body(request, "internal_error", "服务器内部错误"),
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict:
        """路演前预检：课程包、RAG 索引和模型/回退能力。"""
        course = get_course_data()
        rag = get_rag_index()
        llm = runtime_status()
        return {
            "status": "ready" if llm["configured"] else "degraded",
            "curriculum": {
                "course_id": course.course_id,
                "concept_count": len(course.concepts),
                "question_count": len(course.questions),
            },
            "rag": {"segment_count": len(rag.segments), "index_version": rag.index_version},
            "llm": llm,
        }

    app.include_router(demo.router)
    app.include_router(goals.router)
    app.include_router(sessions.router)
    app.include_router(assessments.router)
    app.include_router(exercises.router)
    app.include_router(me.router)
    app.include_router(agent.router)
    app.include_router(tasks.router)
    app.include_router(diagnosis_report.router)
    app.include_router(path_decision.router)
    app.include_router(tutoring_agent.router)
    app.include_router(tutoring_rag.router)
    app.include_router(reflection.router)
    app.include_router(motivation.router)

    return app


app = create_app()
