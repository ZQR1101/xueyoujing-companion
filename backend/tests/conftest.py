"""共享测试夹具：每个测试独立 SQLite 文件 + Alembic 迁移到 head。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.curriculum_import import import_curriculum
from app.infrastructure.database import configure_engine, get_db
from app.infrastructure.models import Concept
from app.main import app as fastapi_app

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _force_mock_llm(monkeypatch):
    """测试固定使用 mock 提供者，不随本地 .env 的 LLM 配置漂移。"""
    from app.infrastructure.config import get_settings

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def engine(tmp_path):
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    configure_engine(engine)

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    yield engine
    engine.dispose()


@pytest.fixture()
def db_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def client(engine, db_factory):
    def override_get_db():
        session = db_factory()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def make_identity(client):
    def _make(display_name: str = "演示学生") -> dict:
        response = client.post(
            "/api/v1/demo-identities",
            json={"display_name": display_name},
            headers={"Idempotency-Key": f"identity-{uuid4().hex}"},
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]

    return _make


@pytest.fixture()
def auth_headers():
    def _headers(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    return _headers


@pytest.fixture()
def curriculum(db_factory):
    """把课程包导入测试库（每测试一次）。"""
    session = db_factory()
    with session.begin():
        import_curriculum(session)


@pytest.fixture()
def seed_concepts(db_factory):
    def _seed(course_id: str = "quadratic", concept_ids: tuple[str, ...] = ("C01", "C02")):
        session = db_factory()
        with session.begin():
            for concept_id in concept_ids:
                session.add(
                    Concept(
                        id=concept_id,
                        course_id=course_id,
                        title=concept_id,
                        prerequisite_ids=[],
                        resource_ids=[],
                    )
                )

    return _seed
