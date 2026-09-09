"""LLM 提供者与网关（§5/§9.4）。

- Provider 只负责"给结构化请求，返回文本+用量"；不触碰数据库。
- Gateway 负责超时、JSON 解析与**最多一次**修复重试（§9.4），
  返回 (parsed, attempts, usage, error)；校验归属与阶段合法性在 coordinator。
- MockProvider 为演示用模拟提供者（离线可演练，model_id=mock 可见标记）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.infrastructure.config import get_settings


@dataclass(frozen=True)
class ProviderResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model_id: str


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    def complete(self, *, system: str, payload: dict, timeout: float) -> ProviderResult: ...


class MockProvider:
    """确定性模拟提供者：默认选合法行动集合的第一个行动。"""

    model_id = "mock"

    def complete(self, *, system: str, payload: dict, timeout: float) -> ProviderResult:
        if payload.get("purpose") == "learning_reflection":
            # 测试/演示提供者只改写规则草稿，不生成新的学习事实或证据 ID。
            draft = payload.get("rule_draft") or {}
            text = json.dumps(
                {
                    "learned": draft.get("learned", []),
                    "still_uncertain": draft.get("still_uncertain", []),
                    "evidence_summary": draft.get("evidence_summary", {}),
                    "learning_characteristics": draft.get("learning_characteristics", []),
                },
                ensure_ascii=False,
            )
            return ProviderResult(
                text=text,
                prompt_tokens=len(json.dumps(payload, ensure_ascii=False)),
                completion_tokens=len(text),
                model_id=self.model_id,
            )
        legal = payload.get("legal_actions") or []
        if legal:
            first = legal[0]
            decision = {
                "action": first["action"],
                "target_id": first.get("target_id"),
                "reason_code": first.get("reason_code", "rule_first_legal"),
                "evidence_ids": [],
                "student_message": first.get("message", "我们按计划继续。"),
            }
        else:
            decision = {
                "action": "finish_session",
                "target_id": None,
                "reason_code": "no_legal_action",
                "evidence_ids": [],
                "student_message": "当前没有可安排的行动。",
            }
        text = json.dumps(decision, ensure_ascii=False)
        return ProviderResult(
            text=text,
            prompt_tokens=len(json.dumps(payload, ensure_ascii=False)),
            completion_tokens=len(text),
            model_id=self.model_id,
        )


class ScriptedProvider:
    """测试用：按脚本依次返回原始文本；耗尽后重复最后一个（stay_on_last）。"""

    def __init__(self, script: list[str], stay_on_last: bool = False):
        self.script = list(script)
        self.index = 0
        self.stay_on_last = stay_on_last
        self.model_id = "scripted"

    def complete(self, *, system: str, payload: dict, timeout: float) -> ProviderResult:
        if self.index < len(self.script):
            text = self.script[self.index]
            self.index += 1
        elif self.stay_on_last and self.script:
            text = self.script[-1]
        else:
            raise LLMError("脚本已耗尽")
        return ProviderResult(
            text=text,
            prompt_tokens=len(json.dumps(payload, ensure_ascii=False)),
            completion_tokens=len(text),
            model_id=self.model_id,
        )


class TimeoutProvider:
    """测试用：模拟模型超时。"""

    model_id = "timeout-mock"

    def complete(self, *, system: str, payload: dict, timeout: float) -> ProviderResult:
        raise httpx.TimeoutException("simulated timeout")


class UnavailableProvider:
    """配置不完整时保留统一网关语义，让业务层可靠进入规则回退。"""

    model_id = "unavailable"

    def __init__(self, reason: str):
        self.reason = reason

    def complete(self, *, system: str, payload: dict, timeout: float) -> ProviderResult:
        raise LLMError(self.reason)


class OpenAICompatProvider:
    """OpenAI 兼容 chat/completions 提供者（真实在线模式）。"""

    def __init__(self, base_url: str, api_key: str, model_id: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_id = model_id

    def complete(self, *, system: str, payload: dict, timeout: float) -> ProviderResult:
        if payload.get("purpose") == "learning_reflection":
            user_prompt = (
                "根据规则草稿润色学习小结，只输出 JSON，字段必须为 learned、still_uncertain、"
                "evidence_summary、learning_characteristics。不得新增知识点、结论或 evidence_event_ids，"
                "不得使用‘完全掌握’‘彻底掌握’‘高置信度掌握’。学生自述只能作为辅助上下文。\n\n"
                + json.dumps(payload, ensure_ascii=False)
            )
        else:
            user_prompt = (
                "你是自适应伴学智能体的教学决策模块。根据给定状态，"
                "只输出一个 JSON 对象：{\"action\": ..., \"target_id\": ..., "
                "\"reason_code\": ..., \"evidence_ids\": [...], \"student_message\": ...}。"
                "action 必须取自 legal_actions；不得输出多余内容。\n\n状态与合法行动：\n"
                + json.dumps(payload, ensure_ascii=False)
            )
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        text = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return ProviderResult(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            model_id=self.model_id,
        )


@dataclass
class GatewayOutcome:
    parsed: dict | None
    attempts: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def total_prompt_tokens(self) -> int:
        return sum(a["prompt_tokens"] for a in self.attempts)

    @property
    def total_completion_tokens(self) -> int:
        return sum(a["completion_tokens"] for a in self.attempts)


class LLMGateway:
    """结构化调用 + 超时 + 最多一次修复重试 + 用量记录。"""

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def decide(
        self,
        *,
        payload: dict,
        validation_error: str | None = None,
        timeout: float | None = None,
        system: str | None = None,
    ) -> GatewayOutcome:
        settings = get_settings()
        timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        system = system or (
            "你是初中数学自适应伴学系统的教学决策模块。只输出 JSON。"
            "action/target/evidence 必须来自给定合法集合；evidence_ids 引用真实存在的证据 ID。"
        )
        outcome = GatewayOutcome(parsed=None)
        last_error: str | None = None
        current_payload = dict(payload)
        if validation_error:
            current_payload["previous_error"] = validation_error

        for attempt_no in (1, 2):
            try:
                result = self.provider.complete(
                    system=system, payload=current_payload, timeout=timeout
                )
            except Exception as exc:  # 超时/网络/脚本耗尽统一按失败处理
                last_error = f"{type(exc).__name__}: {exc}"
                outcome.attempts.append(
                    {"attempt": attempt_no, "error": last_error, "prompt_tokens": 0, "completion_tokens": 0}
                )
                break

            try:
                parsed = _parse_json(result.text)
            except (json.JSONDecodeError, TypeError) as exc:
                last_error = f"invalid_json: {exc}"
                outcome.attempts.append(
                    {
                        "attempt": attempt_no,
                        "error": last_error,
                        "prompt_tokens": result.prompt_tokens,
                        "completion_tokens": result.completion_tokens,
                    }
                )
                current_payload = dict(payload, previous_error=last_error)
                continue

            outcome.attempts.append(
                {
                    "attempt": attempt_no,
                    "text": result.text,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                }
            )
            outcome.usage = {
                "model_id": result.model_id,
                "prompt_tokens": outcome.total_prompt_tokens,
                "completion_tokens": outcome.total_completion_tokens,
            }
            outcome.parsed = parsed
            return outcome

        outcome.error = last_error
        return outcome


def _parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned)


def build_gateway() -> LLMGateway:
    settings = get_settings()
    if settings.llm_provider == "openai":
        if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model_id:
            return LLMGateway(UnavailableProvider(
                "openai 提供者需要 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL_ID"
            ))
        return LLMGateway(
            OpenAICompatProvider(settings.llm_base_url, settings.llm_api_key, settings.llm_model_id)
        )
    if settings.llm_provider == "mock":
        return LLMGateway(MockProvider())
    return LLMGateway(UnavailableProvider(f"未知 LLM_PROVIDER: {settings.llm_provider}"))


def runtime_status() -> dict:
    """不发起外网请求的运行模式预检；绝不返回 API Key。"""
    settings = get_settings()
    configured = settings.llm_provider == "mock" or (
        settings.llm_provider == "openai"
        and bool(settings.llm_base_url and settings.llm_api_key and settings.llm_model_id)
    )
    return {
        "provider": settings.llm_provider,
        "model_id": "mock" if settings.llm_provider == "mock" else settings.llm_model_id,
        "configured": configured,
        "timeout_seconds": settings.llm_timeout_seconds,
        "rule_fallback_available": True,
    }
