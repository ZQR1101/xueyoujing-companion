"""确定性评分（§8）：选择题 + 有限数值输入；禁止 eval。

数值规范化随题配置：
- integer：去空格、允许正负号、整数精确比较
- decimal：去空格、十进制小数，|答案-标准| <= tolerance（默认 1e-9）
- rational：整数 / 小数 / p/q 分数均可，按有理数精确比较（自动约分）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

_INT_RE = re.compile(r"^[+-]?\d+$")
_DEC_RE = re.compile(r"^[+-]?(\d+(\.\d+)?|\.\d+)$")
_RATIONAL_RE = re.compile(r"^[+-]?\d+\s*/\s*\d+$")
_DEFAULT_TOLERANCE = 1e-9


class AnswerFormatError(ValueError):
    """答案无法按题目配置解析（调用方应转 422，不计入评分）。"""


@dataclass(frozen=True)
class GradeResult:
    correct: bool
    error_code: str | None = None


def _clean(text: str) -> str:
    return text.strip().replace("\u3000", "").replace(",", "")


def grade_mcq(answer: str, private_answer: dict, public_options: list) -> GradeResult:
    valid_keys = {option["key"] for option in public_options}
    cleaned = _clean(answer).upper()
    if cleaned not in valid_keys:
        raise AnswerFormatError(f"选项必须是 {sorted(valid_keys)} 之一")
    expected = str(private_answer["value"]).strip().upper()
    return GradeResult(correct=(cleaned == expected))


def _parse_numeric(text: str, config: dict) -> Fraction | float:
    kind = config.get("kind", "rational")
    cleaned = _clean(text)
    if kind == "integer":
        if not _INT_RE.match(cleaned):
            raise AnswerFormatError("该题只接受整数答案")
        return Fraction(int(cleaned))
    if kind == "decimal":
        if not _DEC_RE.match(cleaned):
            raise AnswerFormatError("该题只接受小数或整数答案")
        return float(cleaned)
    # rational：整数、小数、p/q 均可
    if _INT_RE.match(cleaned) or _DEC_RE.match(cleaned):
        return Fraction(cleaned)
    if _RATIONAL_RE.match(cleaned):
        numerator, _, denominator = cleaned.partition("/")
        if int(denominator) == 0:
            raise AnswerFormatError("分母不能为 0")
        return Fraction(int(numerator), int(denominator))
    raise AnswerFormatError("答案格式无法识别（支持整数、小数或 p/q）")


def grade_numeric(answer: str, private_answer: dict, numeric_config: dict | None) -> GradeResult:
    config = numeric_config or {"kind": "rational"}
    expected = _parse_numeric(str(private_answer["value"]), config)
    actual = _parse_numeric(answer, config)
    if isinstance(expected, float) or isinstance(actual, float):
        tolerance = float(config.get("tolerance", _DEFAULT_TOLERANCE))
        return GradeResult(correct=abs(float(actual) - float(expected)) <= tolerance)
    return GradeResult(correct=actual == expected)


def grade_question(question, answer: str) -> GradeResult:
    """question 为 DB Question 模型或含同名字段的字典。"""
    get = question.get if isinstance(question, dict) else lambda name: getattr(question, name)
    if get("type") == "mcq":
        return grade_mcq(answer, get("private_answer"), get("public_options"))
    return grade_numeric(answer, get("private_answer"), get("numeric_config"))
