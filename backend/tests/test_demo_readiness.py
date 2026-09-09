"""Demo readiness and safe LLM degradation."""
from app.infrastructure.config import get_settings
from app.infrastructure.llm.gateway import build_gateway


def test_readyz_reports_curriculum_rag_and_fallback(client, curriculum):
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["curriculum"] == {
        "course_id": "quadratic", "concept_count": 6, "question_count": 300
    }
    assert data["rag"]["segment_count"] > 0
    assert data["rag"]["index_version"]
    assert data["llm"]["provider"] == "mock"
    assert data["llm"]["rule_fallback_available"] is True


def test_incomplete_online_config_degrades_instead_of_raising(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    outcome = build_gateway().decide(payload={"legal_actions": []})
    assert outcome.parsed is None
    assert "LLMError" in (outcome.error or "")
    assert "LLM_API_KEY" in (outcome.error or "")


def test_unknown_provider_degrades_instead_of_silently_using_mock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown-provider")
    get_settings.cache_clear()
    outcome = build_gateway().decide(payload={"legal_actions": []})
    assert outcome.parsed is None
    assert "未知 LLM_PROVIDER" in (outcome.error or "")
