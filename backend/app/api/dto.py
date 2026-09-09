"""外部写入 DTO：全部拒绝未知字段（§6）。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateDemoIdentity(StrictModel):
    display_name: str = Field(min_length=1, max_length=80)


class CreateGoal(StrictModel):
    course_id: str = Field(min_length=1, max_length=40)
    target_concept_ids: list[str] = Field(default_factory=list, max_length=50)
    daily_minutes: int = Field(ge=5, le=120)


class StartDiagnosis(StrictModel):
    expected_version: int = Field(ge=1)


class SubmitAttempt(StrictModel):
    answer: str = Field(min_length=0, max_length=500)
    expected_version: int = Field(ge=1)


class CompleteAssessment(StrictModel):
    expected_version: int = Field(ge=1)


class ReplanGoal(StrictModel):
    reason: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=0)


class StartNextTask(StrictModel):
    expected_version: int = Field(ge=1)


class RequestHint(StrictModel):
    expected_version: int = Field(ge=1)


class RequestSolution(StrictModel):
    expected_version: int = Field(ge=1)


class PauseSession(StrictModel):
    expected_version: int = Field(ge=1)


class ResumeSession(StrictModel):
    expected_version: int = Field(ge=1)


class SendMessage(StrictModel):
    text: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(ge=1)


class SaveReflection(StrictModel):
    text: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)


class GenerateDiagnosisReport(StrictModel):
    """T10-B：生成 AI 学情诊断（无必填字段，预留扩展）。"""


class PathDecisionRequest(StrictModel):
    """T11-B：生成路径决策。expected_version = 当前计划版本（0 表示尚无计划）。"""

    expected_version: int = Field(ge=0)


class SubmitThinking(StrictModel):
    """T12-B：提交思路/困惑，换取启发式反馈与追问（不计掌握证据）。"""

    text: str = Field(min_length=1, max_length=1000)


ALLOWED_CONTENT_TYPES = {"explanation", "example", "hint", "transfer"}


class RagQuery(StrictModel):
    """T13-B：教学检索请求（检索分数只表示资料相关性，不入掌握度）。"""

    query: str = Field(min_length=1, max_length=300)
    content_type: str = Field(default="explanation")
    concept_id: str | None = Field(default=None, max_length=40)
    exercise_id: str | None = Field(default=None, max_length=36)
    error_code: str | None = Field(default=None, max_length=40)
    student_level: str | None = Field(default=None, max_length=20)
    allowed_concept_ids: list[str] | None = Field(default=None, max_length=20)

    @field_validator("content_type")
    @classmethod
    def _check_content_type(cls, v: str) -> str:
        if v not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"content_type 必须是 {sorted(ALLOWED_CONTENT_TYPES)} 之一")
        return v


class GenerateReflection(StrictModel):
    text: str | None = Field(default=None, max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)
    force_llm_failure: bool = False  # 测试 mock provider 回退路径


class MemoryCorrection(StrictModel):
    status: str = Field(pattern="^(disputed|invalidated)$")
