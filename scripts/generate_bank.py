"""题库批量生成（第三批）：参数化模板 × 每族 3 个变体，目标全库 300 题。

设计约定（与课程包既有标准一致）：
- 每个知识点在 F1-F8 之外新增 14 个题族（FAM-<cid>-9 .. -22），每族 3 个变体；
  新题 id 为 Q-<cid>-X01 .. X42（X 恒排在 F1-F8 之后，保证抽题稳定序列不变）；
- 答案全部由代码按题面定义精确计算（整数 / Fraction / 精确小数），不人工填写数字；
- 提示遵循分级：L1 概念提醒 / L2 关键关系（可含题面数字）/ L3 固定"异数字"类比 /
  L4 只给步骤、不含数字与结论；
- 生成后运行泄露自检 + 课程包完整校验，全部通过才写回 questions.json；
  已存在的 id 原样保留（幂等）。

用法：
    cd backend && uv run python ../scripts/generate_bank.py
"""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain import scoring  # noqa: E402
from app.infrastructure.curriculum import load_course, validate_course  # noqa: E402

QUESTIONS_PATH = ROOT / "curriculum" / "quadratic" / "questions.json"


# ---------------------------------------------------------------- 数值格式化


def _dec_places(fr: Fraction) -> int:
    den = fr.denominator
    a = 0
    while den % 2 == 0:
        den //= 2
        a += 1
    b = 0
    while den % 5 == 0:
        den //= 5
        b += 1
    return max(a, b)


def _dec(fr: Fraction) -> str:
    """Fraction → 精确十进制字符串（分母只能含 2/5 质因数）。"""
    places = _dec_places(fr)
    scaled = fr * 10**places
    assert scaled.denominator == 1, f"{fr} 无法精确表示为小数"
    text = str(scaled.numerator)
    sign = "-" if text.startswith("-") else ""
    digits = text.lstrip("-").rjust(places + 1, "0")
    if places == 0:
        return f"{sign}{digits}"
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def _num_text(value: Fraction, kind: str) -> str:
    if kind == "decimal":
        return _dec(value)
    if kind == "rational" and value.denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    return str(int(value))


# ---------------------------------------------------------------- 构建器


class Gen:
    def __init__(self, cid: str):
        self.cid = cid
        self.fam_no = 8  # F1-F8 已存在
        self.idx = 0

    def _next_meta(self) -> tuple[str, str]:
        self.idx += 1
        return f"Q-{self.cid}-X{self.idx:02d}", f"FAM-{self.cid}-{self.fam_no}"

    def mcq(self, purpose, diff, prompt, correct, wrongs, hints, solution):
        assert len(wrongs) == 3 and len(set(wrongs)) == 3, f"选项异常：{prompt}"
        qid, fam = self._next_meta()
        pos = (self.idx - 1) % 4
        keys = ["A", "B", "C", "D"]
        ordered = wrongs[:pos] + [correct] + wrongs[pos:]
        options = [{"key": k, "text": t} for k, t in zip(keys, ordered)]
        return {
            "id": qid, "course_id": "quadratic", "primary_concept_id": self.cid,
            "family_id": fam, "type": "mcq", "purpose": purpose, "difficulty": diff,
            "prompt": prompt, "public_options": options,
            "private_answer": {"kind": "option", "value": keys[pos]},
            "private_hints": hints, "numeric_config": None, "version": 1,
            "private_solution": solution.replace("{key}", keys[pos]),
        }

    def numeric(self, purpose, diff, prompt, value: Fraction, kind, hints, solution):
        qid, fam = self._next_meta()
        return {
            "id": qid, "course_id": "quadratic", "primary_concept_id": self.cid,
            "family_id": fam, "type": "numeric", "purpose": purpose, "difficulty": diff,
            "prompt": prompt, "public_options": [],
            "private_answer": {"kind": "numeric", "value": _num_text(value, kind)},
            "private_hints": hints, "numeric_config": {"kind": kind}, "version": 1,
            "private_solution": solution.replace("{value}", _num_text(value, kind)),
        }


def family(gen: Gen, purpose, diff, l1: str, l3: str, l4: str, variants: list[dict]) -> list[dict]:
    """variants 每项：{prompt, l2, solution, 以及 mcq(correct, wrongs) 或 numeric(value, cfg)}。"""
    gen.fam_no += 1  # idx 跨题族连续递增（X01..X42）
    out = []
    for v in variants:
        hints = [l1, v["l2"], l3, l4]
        if "correct" in v:
            out.append(gen.mcq(purpose, diff, v["prompt"], v["correct"], v["wrongs"], hints, v["solution"]))
        else:
            out.append(gen.numeric(purpose, diff, v["prompt"], v["value"], v["cfg"], hints, v["solution"]))
    return out


def F(p: Fraction) -> Fraction:
    return Fraction(p)


# ---------------------------------------------------------------- C01 平方与代入


def build_c01(g: Gen) -> list[dict]:
    qs: list[dict] = []

    # F9 screening：(-a)²
    qs += family(g, "screening", 1,
                 "想一想：负数的平方，符号会变成什么？",
                 "类比：(-3)² = 9，两个相同负数相乘得正数。",
                 "先算 a×a，再按负负得正确定符号；把得数代回选项核对。",
                 [
                     {"prompt": "计算 (-4)² 的值。", "correct": "16", "wrongs": ["-16", "-8", "8"],
                      "l2": "(-4)² = (-4)×(-4)，负负得正。",
                      "solution": "(-4)² = (-4)×(-4)。负负得正，4×4=16，所以 (-4)²=16，选 {key}。"},
                     {"prompt": "计算 (-9)² 的值。", "correct": "81", "wrongs": ["-81", "-18", "18"],
                      "l2": "(-9)² = (-9)×(-9)，负负得正。",
                      "solution": "(-9)² = (-9)×(-9)。负负得正，9×9=81，所以 (-9)²=81，选 {key}。"},
                     {"prompt": "计算 (-12)² 的值。", "correct": "144", "wrongs": ["-144", "-24", "24"],
                      "l2": "(-12)² = (-12)×(-12)，负负得正。",
                      "solution": "(-12)² = (-12)×(-12)。负负得正，12×12=144，所以 (-12)²=144，选 {key}。"},
                 ])

    # F10 screening：分数平方
    qs += family(g, "screening", 2,
                 "x² 就是 x·x，把 x 换成给定分数再相乘。",
                 "类比：(1/2)² = 1/4，分数平方是分子分母各自平方。",
                 "分子相乘、分母相乘，结果化为最简分数（也可写成小数）。",
                 [
                     {"prompt": "若 x = 2/3，求代数式 x² 的值。（可用分数或小数作答）", "value": F(4) / 9, "cfg": "rational",
                      "l2": "(2/3)² = (2/3)×(2/3)，分子乘分子、分母乘分母。",
                      "solution": "x² = (2/3)×(2/3) = 4/9（分子 2×2，分母 3×3），也可写成小数 0.4424…，精确值为 {value}。"},
                     {"prompt": "若 x = 3/5，求代数式 x² 的值。（可用分数或小数作答）", "value": F(9) / 25, "cfg": "rational",
                      "l2": "(3/5)² = (3/5)×(3/5)，分子乘分子、分母乘分母。",
                      "solution": "x² = (3/5)×(3/5) = 9/25（分子 3×3，分母 5×5），精确值为 {value}。"},
                     {"prompt": "若 x = 4/3，求代数式 x² 的值。（可用分数或小数作答）", "value": F(16) / 9, "cfg": "rational",
                      "l2": "(4/3)² = (4/3)×(4/3)，分子乘分子、分母乘分母。",
                      "solution": "x² = (4/3)×(4/3) = 16/9（分子 4×4，分母 3×3，是大于 1 的假分数），精确值为 {value}。"},
                 ])

    # F11 transfer：-a²（无括号）
    qs += family(g, "transfer", 2,
                 "-a² 和 (-a)² 一样吗？括号决定符号是否参与平方。",
                 "类比：-2² = -4，而 (-2)² = 4，两者不同。",
                 "先算 a×a，再在结果前添上负号。",
                 [
                     {"prompt": "计算 -3² 的值。（注意：这次没有括号！）", "value": F(-9), "cfg": "integer",
                      "l2": "-3² 表示 3² 的相反数，即 -(3×3)。",
                      "solution": "-3² = -(3×3)。平方只作用于 3，负号在平方之外，所以 -3² = {value}（注意它与 (-3)² = 9 不同）。"},
                     {"prompt": "计算 -8² 的值。（注意：这次没有括号！）", "value": F(-64), "cfg": "integer",
                      "l2": "-8² 表示 8² 的相反数，即 -(8×8)。",
                      "solution": "-8² = -(8×8)。平方只作用于 8，负号在平方之外，所以 -8² = {value}（注意它与 (-8)² = 64 不同）。"},
                     {"prompt": "计算 -11² 的值。（注意：这次没有括号！）", "value": F(-121), "cfg": "integer",
                      "l2": "-11² 表示 11² 的相反数，即 -(11×11)。",
                      "solution": "-11² = -(11×11)。平方只作用于 11，负号在平方之外，所以 -11² = {value}（注意它与 (-11)² = 121 不同）。"},
                 ])

    # F12 practice：判断正确算式
    qs += family(g, "practice", 2,
                 "逐项检查：括号决定符号是否参与平方。",
                 "类比：-2² = -4，而 (-2)² = 4。",
                 "逐项核对符号与数值，只有一项全对。",
                 [
                     {"prompt": "下列计算正确的是（　）。",
                      "correct": "(-3)² = 9", "wrongs": ["-3² = 9", "(-3)² = -9", "-(-3)² = 9"],
                      "l2": "负数在括号里平方得正；符号在括号外的，结果是负的。",
                      "solution": "(-3)² = 9（正确）；-3² = -9；(-3)² ≠ -9；-(-3)² = -9。故选 {key}。"},
                     {"prompt": "下列计算正确的是（　）。",
                      "correct": "(-5)² = 25", "wrongs": ["-5² = 25", "(-5)² = -25", "-(-5)² = 25"],
                      "l2": "负数在括号里平方得正；符号在括号外的，结果是负的。",
                      "solution": "(-5)² = 25（正确）；-5² = -25；(-5)² ≠ -25；-(-5)² = -25。故选 {key}。"},
                     {"prompt": "下列计算正确的是（　）。",
                      "correct": "(-6)² = 36", "wrongs": ["-6² = 36", "(-6)² = -36", "-(-6)² = 36"],
                      "l2": "负数在括号里平方得正；符号在括号外的，结果是负的。",
                      "solution": "(-6)² = 36（正确）；-6² = -36；(-6)² ≠ -36；-(-6)² = -36。故选 {key}。"},
                 ])

    # F13 screening：2x²
    qs += family(g, "screening", 2,
                 "按顺序代入：先算乘方，再乘系数。",
                 "类比：y = 3x² 在 x = 2 时是 3×4。",
                 "算出平方后乘系数，即为 y。",
                 [
                     {"prompt": "已知 y = 2x²，当 x = 3 时，y = ？", "value": F(18), "cfg": "integer",
                      "l2": "x² = 9，2x² = 2×9。",
                      "solution": "y = 2×3² = 2×9 = {value}。"},
                     {"prompt": "已知 y = 2x²，当 x = 5 时，y = ？", "value": F(50), "cfg": "integer",
                      "l2": "x² = 25，2x² = 2×25。",
                      "solution": "y = 2×5² = 2×25 = {value}。"},
                     {"prompt": "已知 y = 2x²，当 x = 6 时，y = ？", "value": F(72), "cfg": "integer",
                      "l2": "x² = 36，2x² = 2×36。",
                      "solution": "y = 2×6² = 2×36 = {value}。"},
                 ])

    # F14 practice：3x²，负数代入
    qs += family(g, "practice", 2,
                 "代入负数时记得加括号：x² = (-a)²。",
                 "类比：x = -3 时 x² = 9。",
                 "算出平方后乘系数，即为 y。",
                 [
                     {"prompt": "已知 y = 3x²，当 x = -2 时，y = ？", "value": F(12), "cfg": "integer",
                      "l2": "(-2)² = 4，3x² = 3×4。",
                      "solution": "y = 3×(-2)² = 3×4 = {value}。"},
                     {"prompt": "已知 y = 3x²，当 x = -4 时，y = ？", "value": F(48), "cfg": "integer",
                      "l2": "(-4)² = 16，3x² = 3×16。",
                      "solution": "y = 3×(-4)² = 3×16 = {value}。"},
                     {"prompt": "已知 y = 3x²，当 x = -5 时，y = ？", "value": F(75), "cfg": "integer",
                      "l2": "(-5)² = 25，3x² = 3×25。",
                      "solution": "y = 3×(-5)² = 3×25 = {value}。"},
                 ])

    # F15 practice：负分数平方
    qs += family(g, "practice", 3,
                 "负分数平方先加括号：(-p/q)²。",
                 "类比：(1/2)² = 1/4。",
                 "分子相乘、分母相乘，结果化为最简分数或小数。",
                 [
                     {"prompt": "若 x = -1/3，求 x² 的值。（可用分数或小数作答）", "value": F(1) / 9, "cfg": "rational",
                      "l2": "相反数的平方相等：(-1/3)² = (1/3)²。",
                      "solution": "x² = (-1/3)² = (1/3)² = {value}。"},
                     {"prompt": "若 x = -2/5，求 x² 的值。（可用分数或小数作答）", "value": F(4) / 25, "cfg": "rational",
                      "l2": "相反数的平方相等：(-2/5)² = (2/5)²。",
                      "solution": "x² = (-2/5)² = (2/5)² = {value}。"},
                     {"prompt": "若 x = -3/4，求 x² 的值。（可用分数或小数作答）", "value": F(9) / 16, "cfg": "rational",
                      "l2": "相反数的平方相等：(-3/4)² = (3/4)²。",
                      "solution": "x² = (-3/4)² = (3/4)² = {value}。"},
                 ])

    # F16 transfer：x² - x
    qs += family(g, "transfer", 2,
                 "先算 x² 与 x，最后相减。",
                 "类比：y = x² - x 在 x = 3 时是 9 - 3。",
                 "最后把两个结果相减，即为 y。",
                 [
                     {"prompt": "已知 y = x² - x，当 x = 4 时，y = ？", "value": F(12), "cfg": "integer",
                      "l2": "x² = 16；x = 4。",
                      "solution": "y = 4² - 4 = 16 - 4 = {value}。"},
                     {"prompt": "已知 y = x² - x，当 x = 6 时，y = ？", "value": F(30), "cfg": "integer",
                      "l2": "x² = 36；x = 6。",
                      "solution": "y = 6² - 6 = 36 - 6 = {value}。"},
                     {"prompt": "已知 y = x² - x，当 x = 9 时，y = ？", "value": F(72), "cfg": "integer",
                      "l2": "x² = 81；x = 9。",
                      "solution": "y = 9² - 9 = 81 - 9 = {value}。"},
                 ])

    # F17 transfer：x² + x（负数代入）
    qs += family(g, "transfer", 2,
                 "代入负数加括号：先算 x²，再算 x，最后相加。",
                 "类比：x = -2 时 x² + x = 4 - 2。",
                 "先算平方，再减去 |x|（加负数即减），即为 y。",
                 [
                     {"prompt": "已知 y = x² + x，当 x = -3 时，y = ？", "value": F(6), "cfg": "integer",
                      "l2": "x² = 9；x = -3，所以 x² + x = 9 - 3。",
                      "solution": "y = (-3)² + (-3) = 9 - 3 = {value}。"},
                     {"prompt": "已知 y = x² + x，当 x = -5 时，y = ？", "value": F(20), "cfg": "integer",
                      "l2": "x² = 25；x = -5，所以 x² + x = 25 - 5。",
                      "solution": "y = (-5)² + (-5) = 25 - 5 = {value}。"},
                     {"prompt": "已知 y = x² + x，当 x = -8 时，y = ？", "value": F(56), "cfg": "integer",
                      "l2": "x² = 64；x = -8，所以 x² + x = 64 - 8。",
                      "solution": "y = (-8)² + (-8) = 64 - 8 = {value}。"},
                 ])

    # F18 review：正方形面积
    qs += family(g, "review", 1,
                 "面积 = 边长²。",
                 "类比：边长 7 时面积是 49。",
                 "直接计算边长×边长，结果即为面积。",
                 [
                     {"prompt": "正方形边长为 13 米，面积是多少平方米？", "value": F(169), "cfg": "integer",
                      "l2": "面积 = 13×13。",
                      "solution": "面积 = 13×13 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 21 米，面积是多少平方米？", "value": F(441), "cfg": "integer",
                      "l2": "面积 = 21×21。",
                      "solution": "面积 = 21×21 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 25 米，面积是多少平方米？", "value": F(625), "cfg": "integer",
                      "l2": "面积 = 25×25。",
                      "solution": "面积 = 25×25 = {value}（平方米）。"},
                 ])

    # F19 review：(x+1)² - x²
    qs += family(g, "review", 3,
                 "分别算 (x+1)² 与 x²，再相减。",
                 "类比：x = 2 时是 3² - 2²。",
                 "算出两个平方后相减，即为结果。",
                 [
                     {"prompt": "已知 x = 5，求 (x + 1)² - x² 的值。", "value": F(11), "cfg": "integer",
                      "l2": "(x+1)² = 36；x² = 25。",
                      "solution": "(5+1)² - 5² = 36 - 25 = {value}。"},
                     {"prompt": "已知 x = 10，求 (x + 1)² - x² 的值。", "value": F(21), "cfg": "integer",
                      "l2": "(x+1)² = 121；x² = 100。",
                      "solution": "(10+1)² - 10² = 121 - 100 = {value}。"},
                     {"prompt": "已知 x = 20，求 (x + 1)² - x² 的值。", "value": F(41), "cfg": "integer",
                      "l2": "(x+1)² = 441；x² = 400。",
                      "solution": "(20+1)² - 20² = 441 - 400 = {value}。"},
                 ])

    # F20 transfer：x² = k 取正根
    qs += family(g, "transfer", 2,
                 "什么数的平方等于给定的数？",
                 "类比：x² = 25 时 x = 5。",
                 "想几乘几等于那个数；因为 x > 0，取正值。",
                 [
                     {"prompt": "已知 x² = 36 且 x > 0，求 x 的值。", "value": F(6), "cfg": "integer",
                      "l2": "x > 0，取正的平方根。",
                      "solution": "由 x² = 36 且 x > 0，得 x = {value}。"},
                     {"prompt": "已知 x² = 81 且 x > 0，求 x 的值。", "value": F(9), "cfg": "integer",
                      "l2": "x > 0，取正的平方根。",
                      "solution": "由 x² = 81 且 x > 0，得 x = {value}。"},
                     {"prompt": "已知 x² = 144 且 x > 0，求 x 的值。", "value": F(12), "cfg": "integer",
                      "l2": "x > 0，取正的平方根。",
                      "solution": "由 x² = 144 且 x > 0，得 x = {value}。"},
                 ])

    # F21 review：判断恒等式
    qs += family(g, "review", 2,
                 "逐项检查：括号决定符号是否参与平方。",
                 "类比：-2² = -4，而 (-2)² = 4。",
                 "对照每一项的符号与数值，只有一项完全正确。",
                 [
                     {"prompt": "下列各式中，一定成立的是（　）。",
                      "correct": "(-3)² = 3²", "wrongs": ["-3² = 3²", "(-3)² = -3²", "-(-3)² = 3²"],
                      "l2": "相反数的平方相等：(-a)² = a²。",
                      "solution": "(-3)² = 3² = 9（正确）；-3² = -9；-(-3)² = -9。故选 {key}。"},
                     {"prompt": "下列各式中，一定成立的是（　）。",
                      "correct": "(-5)² = 5²", "wrongs": ["-5² = 5²", "(-5)² = -5²", "-(-5)² = 5²"],
                      "l2": "相反数的平方相等：(-a)² = a²。",
                      "solution": "(-5)² = 5² = 25（正确）；-5² = -25；-(-5)² = -25。故选 {key}。"},
                     {"prompt": "下列各式中，一定成立的是（　）。",
                      "correct": "(-6)² = 6²", "wrongs": ["-6² = 6²", "(-6)² = -6²", "-(-6)² = 6²"],
                      "l2": "相反数的平方相等：(-a)² = a²。",
                      "solution": "(-6)² = 6² = 36（正确）；-6² = -36；-(-6)² = -36。故选 {key}。"},
                 ])

    # F22 practice：小数平方
    qs += family(g, "practice", 2,
                 "x² 就是 x·x。",
                 "类比：(0.3)² = 0.09。",
                 "先按整数相乘，再点上小数点（看两个因数共几位小数）。",
                 [
                     {"prompt": "若 x = 0.2，求 x² 的值。（用小数作答）", "value": F(1) / 25, "cfg": "decimal",
                      "l2": "0.2² = 0.2×0.2，两个因数共两位小数。",
                      "solution": "x² = 0.2×0.2 = {value}。"},
                     {"prompt": "若 x = 1.5，求 x² 的值。（用小数作答）", "value": F(9) / 4, "cfg": "decimal",
                      "l2": "1.5² = 1.5×1.5，两个因数共两位小数。",
                      "solution": "x² = 1.5×1.5 = {value}。"},
                     {"prompt": "若 x = 2.5，求 x² 的值。（用小数作答）", "value": F(25) / 4, "cfg": "decimal",
                      "l2": "2.5² = 2.5×2.5，两个因数共两位小数。",
                      "solution": "x² = 2.5×2.5 = {value}。"},
                 ])

    return qs


# ---------------------------------------------------------------- C02 函数输入输出


def build_c02(g: Gen) -> list[dict]:
    qs: list[dict] = []

    # F9 screening：kx + c
    qs += family(g, "screening", 1,
                 "把 x 的值代入 kx + c，先算乘法再算加法。",
                 "类比：y = 2x - 1 在 x = 3 时先算 2×3。",
                 "把乘积算出后加 c，与选项对照。",
                 [
                     {"prompt": "已知 y = 3x + 1，当 x = 4 时，y = ？", "correct": "13", "wrongs": ["12", "-11", "5"],
                      "l2": "3x 表示 3×4 = 12。",
                      "solution": "y = 3×4 + 1 = 12 + 1 = 13，选 {key}。"},
                     {"prompt": "已知 y = 5x + 3，当 x = 2 时，y = ？", "correct": "13", "wrongs": ["10", "-7", "5"],
                      "l2": "5x 表示 5×2 = 10。",
                      "solution": "y = 5×2 + 3 = 10 + 3 = 13，选 {key}。"},
                     {"prompt": "已知 y = 4x + 2，当 x = 3 时，y = ？", "correct": "14", "wrongs": ["12", "-10", "5"],
                      "l2": "4x 表示 4×3 = 12。",
                      "solution": "y = 4×3 + 2 = 12 + 2 = 14，选 {key}。"},
                 ])

    # F10 practice：x² + c
    qs += family(g, "practice", 1,
                 "先算乘方 x²，再加常数项。",
                 "类比：y = x² + 1 在 x = 3 时是 9 + 1。",
                 "最后做加法，即为 y。",
                 [
                     {"prompt": "已知 y = x² + 3，当 x = 4 时，y = ？", "value": F(19), "cfg": "integer",
                      "l2": "x² = 16。",
                      "solution": "y = 4² + 3 = 16 + 3 = {value}。"},
                     {"prompt": "已知 y = x² + 5，当 x = 6 时，y = ？", "value": F(41), "cfg": "integer",
                      "l2": "x² = 36。",
                      "solution": "y = 6² + 5 = 36 + 5 = {value}。"},
                     {"prompt": "已知 y = x² + 7，当 x = 2 时，y = ？", "value": F(11), "cfg": "integer",
                      "l2": "x² = 4。",
                      "solution": "y = 2² + 7 = 4 + 7 = {value}。"},
                 ])

    # F11 transfer：x² + c，负数代入（mcq）
    qs += family(g, "transfer", 2,
                 "负数代入先平方：(-t)²。",
                 "类比：y = x² + 1 在 x = -2 时先算 (-2)² = 4。",
                 "算出平方后再加 c，与选项对照。",
                 [
                     {"prompt": "已知 y = x² + 1，当 x = -3 时，y = ？", "correct": "10",
                      "wrongs": ["8", "-8", "-10"],
                      "l2": "(-3)² = 9。",
                      "solution": "y = (-3)² + 1 = 9 + 1 = 10，选 {key}。"},
                     {"prompt": "已知 y = x² + 2，当 x = -4 时，y = ？", "correct": "18",
                      "wrongs": ["14", "-14", "-18"],
                      "l2": "(-4)² = 16。",
                      "solution": "y = (-4)² + 2 = 16 + 2 = 18，选 {key}。"},
                     {"prompt": "已知 y = x² + 5，当 x = -2 时，y = ？", "correct": "9",
                      "wrongs": ["-1", "1", "-9"],
                      "l2": "(-2)² = 4。",
                      "solution": "y = (-2)² + 5 = 4 + 5 = 9，选 {key}。"},
                 ])

    # F12 practice：(x-h)²+k 在 h+d 处
    qs += family(g, "practice", 2,
                 "先算括号里的 x - h，再平方，最后加 k。",
                 "类比：y = (x-1)²+2 在 x = 3 时是 2² + 2。",
                 "算出平方后加 k，即为 y。",
                 [
                     {"prompt": "已知 y = (x - 2)² + 1，当 x = 5 时，y = ？", "value": F(10), "cfg": "integer",
                      "l2": "x - 2 = 3，平方项是 9。",
                      "solution": "y = (5-2)² + 1 = 9 + 1 = {value}。"},
                     {"prompt": "已知 y = (x - 5)² + 4，当 x = 7 时，y = ？", "value": F(8), "cfg": "integer",
                      "l2": "x - 5 = 2，平方项是 4。",
                      "solution": "y = (7-5)² + 4 = 4 + 4 = {value}。"},
                     {"prompt": "已知 y = (x - 1)² + 3，当 x = 5 时，y = ？", "value": F(19), "cfg": "integer",
                      "l2": "x - 1 = 4，平方项是 16。",
                      "solution": "y = (5-1)² + 3 = 16 + 3 = {value}。"},
                 ])

    # F13 screening：顶点处取值（(x+h)²-k 在 x=-h）
    qs += family(g, "screening", 1,
                 "代入 x = -h，先算括号里的 x + h。",
                 "类比：y = (x+2)²-5 在 x = -2 时平方项为 0。",
                 "平方项为 0，y 就等于减去 k 后的结果，即常数项本身（注意符号）。",
                 [
                     {"prompt": "已知 y = (x + 3)² - 2，当 x = -3 时，y = ？", "value": F(-2), "cfg": "integer",
                      "l2": "x + 3 = -3 + 3 = 0，平方项为 0。",
                      "solution": "x = -3 时 x + 3 = 0，y = 0 - 2 = {value}。"},
                     {"prompt": "已知 y = (x + 5)² - 4，当 x = -5 时，y = ？", "value": F(-4), "cfg": "integer",
                      "l2": "x + 5 = -5 + 5 = 0，平方项为 0。",
                      "solution": "x = -5 时 x + 5 = 0，y = 0 - 4 = {value}。"},
                     {"prompt": "已知 y = (x + 2)² - 6，当 x = -2 时，y = ？", "value": F(-6), "cfg": "integer",
                      "l2": "x + 2 = -2 + 2 = 0，平方项为 0。",
                      "solution": "x = -2 时 x + 2 = 0，y = 0 - 6 = {value}。"},
                 ])

    # F14 practice：x² - px
    qs += family(g, "practice", 2,
                 "先算 x²，再算 px，最后相减。",
                 "类比：y = x² - 2x 在 x = 3 时是 9 - 6。",
                 "最后把两个结果相减，即为 y。",
                 [
                     {"prompt": "已知 y = x² - 2x，当 x = 5 时，y = ？", "value": F(15), "cfg": "integer",
                      "l2": "x² = 25；2x = 10。",
                      "solution": "y = 5² - 2×5 = 25 - 10 = {value}。"},
                     {"prompt": "已知 y = x² - 3x，当 x = 4 时，y = ？", "value": F(4), "cfg": "integer",
                      "l2": "x² = 16；3x = 12。",
                      "solution": "y = 4² - 3×4 = 16 - 12 = {value}。"},
                     {"prompt": "已知 y = x² - 5x，当 x = 6 时，y = ？", "value": F(6), "cfg": "integer",
                      "l2": "x² = 36；5x = 30。",
                      "solution": "y = 6² - 5×6 = 36 - 30 = {value}。"},
                 ])

    # F15 transfer：x² + px + q
    qs += family(g, "transfer", 3,
                 "按顺序代入：先乘方，再乘除，最后加减。",
                 "类比：y = x² - 2x + 1 在 x = 3 时是 9 - 6 + 1。",
                 "把三项按顺序加减，即为 y。",
                 [
                     {"prompt": "已知 y = x² + 2x + 1，当 x = 4 时，y = ？", "value": F(25), "cfg": "integer",
                      "l2": "x² = 16；2x = 8。",
                      "solution": "y = 4² + 2×4 + 1 = 16 + 8 + 1 = {value}。"},
                     {"prompt": "已知 y = x² + 3x + 2，当 x = 3 时，y = ？", "value": F(20), "cfg": "integer",
                      "l2": "x² = 9；3x = 9。",
                      "solution": "y = 3² + 3×3 + 2 = 9 + 9 + 2 = {value}。"},
                     {"prompt": "已知 y = x² + x + 5，当 x = 5 时，y = ？", "value": F(35), "cfg": "integer",
                      "l2": "x² = 25；x = 5。",
                      "solution": "y = 5² + 5 + 5 = 25 + 5 + 5 = {value}。"},
                 ])

    # F16 screening：a(x-h)²
    qs += family(g, "screening", 1,
                 "先算括号差，再平方，最后乘系数 a。",
                 "类比：y = 2(x-1)² 在 x = 3 时是 2×4。",
                 "算出平方后乘 a，即为 y。",
                 [
                     {"prompt": "已知 y = 2(x - 1)²，当 x = 4 时，y = ？", "value": F(18), "cfg": "integer",
                      "l2": "x - 1 = 3，平方项是 9。",
                      "solution": "y = 2×(4-1)² = 2×9 = {value}。"},
                     {"prompt": "已知 y = 3(x - 2)²，当 x = 4 时，y = ？", "value": F(12), "cfg": "integer",
                      "l2": "x - 2 = 2，平方项是 4。",
                      "solution": "y = 3×(4-2)² = 3×4 = {value}。"},
                     {"prompt": "已知 y = 4(x - 3)²，当 x = 4 时，y = ？", "value": F(4), "cfg": "integer",
                      "l2": "x - 3 = 1，平方项是 1。",
                      "solution": "y = 4×(4-3)² = 4×1 = {value}。"},
                 ])

    # F17 transfer：(x+1)(x-1)
    qs += family(g, "transfer", 3,
                 "分别算两个括号，再相乘。",
                 "类比：x = 3 时是 4×2。",
                 "把两个结果相乘，即为 y。",
                 [
                     {"prompt": "已知 y = (x + 1)(x - 1)，当 x = 5 时，y = ？", "value": F(24), "cfg": "integer",
                      "l2": "x + 1 = 6；x - 1 = 4。",
                      "solution": "y = (5+1)×(5-1) = 6×4 = {value}。"},
                     {"prompt": "已知 y = (x + 1)(x - 1)，当 x = 7 时，y = ？", "value": F(48), "cfg": "integer",
                      "l2": "x + 1 = 8；x - 1 = 6。",
                      "solution": "y = (7+1)×(7-1) = 8×6 = {value}。"},
                     {"prompt": "已知 y = (x + 1)(x - 1)，当 x = 9 时，y = ？", "value": F(80), "cfg": "integer",
                      "l2": "x + 1 = 10；x - 1 = 8。",
                      "solution": "y = (9+1)×(9-1) = 10×8 = {value}。"},
                 ])

    # F18 transfer：由 y = k 反找 x（mcq）
    qs += family(g, "transfer", 2,
                 "什么数的平方等于给定的 y 值？",
                 "类比：y = 4 时 x = 2 或 x = -2。",
                 "想想两个互为相反数的候选值是否都满足 y = k，再对照选项。",
                 [
                     {"prompt": "已知 y = x²，当 y = 16 时，x = ？", "correct": "x = 4 或 x = -4",
                      "wrongs": ["x = 4", "x = -4", "不存在这样的 x"],
                      "l2": "平方等于 16 的数有两个，互为相反数。",
                      "solution": "4² = 16 且 (-4)² = 16，所以 x = 4 或 x = -4，选 {key}。"},
                     {"prompt": "已知 y = x²，当 y = 49 时，x = ？", "correct": "x = 7 或 x = -7",
                      "wrongs": ["x = 7", "x = -7", "不存在这样的 x"],
                      "l2": "平方等于 49 的数有两个，互为相反数。",
                      "solution": "7² = 49 且 (-7)² = 49，所以 x = 7 或 x = -7，选 {key}。"},
                     {"prompt": "已知 y = x²，当 y = 100 时，x = ？", "correct": "x = 10 或 x = -10",
                      "wrongs": ["x = 10", "x = -10", "不存在这样的 x"],
                      "l2": "平方等于 100 的数有两个，互为相反数。",
                      "solution": "10² = 100 且 (-10)² = 100，所以 x = 10 或 x = -10，选 {key}。"},
                 ])

    # F19 practice：小数代入
    qs += family(g, "practice", 3,
                 "先算 x²，再算 0.5x，最后相加。",
                 "类比：x = 0.1 时 x² = 0.01。",
                 "算出两部分后相加，写成小数。",
                 [
                     {"prompt": "已知 y = x² + 0.5x，当 x = 0.4 时，y = ？（用小数作答）", "value": F(9) / 25, "cfg": "decimal",
                      "l2": "x² = 0.16；0.5x = 0.2。",
                      "solution": "y = 0.16 + 0.2 = {value}。"},
                     {"prompt": "已知 y = x² + 0.5x，当 x = 0.2 时，y = ？（用小数作答）", "value": F(7) / 50, "cfg": "decimal",
                      "l2": "x² = 0.04；0.5x = 0.1。",
                      "solution": "y = 0.04 + 0.1 = {value}。"},
                     {"prompt": "已知 y = x² + 0.5x，当 x = 0.6 时，y = ？（用小数作答）", "value": F(33) / 50, "cfg": "decimal",
                      "l2": "x² = 0.36；0.5x = 0.3。",
                      "solution": "y = 0.36 + 0.3 = {value}。"},
                 ])

    # F20 review：(x-h)²+k 在 h-d 处
    qs += family(g, "review", 2,
                 "x = h - d 时括号里是负数，平方后为正。",
                 "类比：y = (x-5)²+1 在 x = 2 时是 (-3)² + 1。",
                 "算出平方后加 k，即为 y。",
                 [
                     {"prompt": "已知 y = (x - 4)² + 2，当 x = 1 时，y = ？", "value": F(11), "cfg": "integer",
                      "l2": "x - 4 = -3，平方项是 9。",
                      "solution": "y = (1-4)² + 2 = 9 + 2 = {value}。"},
                     {"prompt": "已知 y = (x - 6)² + 1，当 x = 4 时，y = ？", "value": F(5), "cfg": "integer",
                      "l2": "x - 6 = -2，平方项是 4。",
                      "solution": "y = (4-6)² + 1 = 4 + 1 = {value}。"},
                     {"prompt": "已知 y = (x - 3)² + 4，当 x = -2 时，y = ？", "value": F(29), "cfg": "integer",
                      "l2": "x - 3 = -5，平方项是 25。",
                      "solution": "y = (-2-3)² + 4 = 25 + 4 = {value}。"},
                 ])

    # F21 review：2x² - x + 3，负数代入
    qs += family(g, "review", 2,
                 "代入负数加括号，先算乘方。",
                 "类比：在 x = -4 时是 2×16 + 4 + 3。",
                 "把三项按顺序加减，即为 y。",
                 [
                     {"prompt": "已知 y = 2x² - x + 3，当 x = -1 时，y = ？", "value": F(6), "cfg": "integer",
                      "l2": "x² = 1，2x² = 2；-x = +1。",
                      "solution": "y = 2×(-1)² - (-1) + 3 = 2 + 1 + 3 = {value}。"},
                     {"prompt": "已知 y = 2x² - x + 3，当 x = -2 时，y = ？", "value": F(13), "cfg": "integer",
                      "l2": "x² = 4，2x² = 8；-x = +2。",
                      "solution": "y = 2×(-2)² - (-2) + 3 = 8 + 2 + 3 = {value}。"},
                     {"prompt": "已知 y = 2x² - x + 3，当 x = -3 时，y = ？", "value": F(24), "cfg": "integer",
                      "l2": "x² = 9，2x² = 18；-x = +3。",
                      "solution": "y = 2×(-3)² - (-3) + 3 = 18 + 3 + 3 = {value}。"},
                 ])

    # F22 review：文字题 x² + 3 = k
    qs += family(g, "review", 2,
                 "把文字写成式子：x² + 3 = 给定的数。",
                 "类比：x² + 3 = 12 时 x = 3。",
                 "先移项求出平方值，再想几乘几等于它，取正值。",
                 [
                     {"prompt": "已知 x² + 3 = 19 且 x > 0，求 x 的值。", "value": F(4), "cfg": "integer",
                      "l2": "x² = 19 - 3 = 16。",
                      "solution": "x² = 19 - 3 = 16，x > 0，所以 x = {value}。"},
                     {"prompt": "已知 x² + 3 = 28 且 x > 0，求 x 的值。", "value": F(5), "cfg": "integer",
                      "l2": "x² = 28 - 3 = 25。",
                      "solution": "x² = 28 - 3 = 25，x > 0，所以 x = {value}。"},
                     {"prompt": "已知 x² + 3 = 52 且 x > 0，求 x 的值。", "value": F(7), "cfg": "integer",
                      "l2": "x² = 52 - 3 = 49。",
                      "solution": "x² = 52 - 3 = 49，x > 0，所以 x = {value}。"},
                 ])

    return qs


# ---------------------------------------------------------------- C03 二次函数图像


def build_c03(g: Gen) -> list[dict]:
    qs: list[dict] = []

    # F9 screening：y = x² + k 顶点（mcq）
    qs += family(g, "screening", 1,
                 "y = x² + k 的图像是把 y = x² 上下平移 k 个单位。",
                 "类比：y = x² + 1 的顶点是 (0, 1)。",
                 "顶点横坐标不变，纵坐标取常数项；写成坐标后对照选项。",
                 [
                     {"prompt": "抛物线 y = x² - 5 的顶点坐标是（　）。", "correct": "(0, -5)",
                      "wrongs": ["(0, 5)", "(-5, 0)", "(5, 0)"],
                      "l2": "y = x² - 5 的常数项是 -5。",
                      "solution": "y = x² - 5 的顶点是 (0, -5)，选 {key}。"},
                     {"prompt": "抛物线 y = x² + 2 的顶点坐标是（　）。", "correct": "(0, 2)",
                      "wrongs": ["(0, -2)", "(2, 0)", "(-2, 0)"],
                      "l2": "y = x² + 2 的常数项是 2。",
                      "solution": "y = x² + 2 的顶点是 (0, 2)，选 {key}。"},
                     {"prompt": "抛物线 y = x² + 6 的顶点坐标是（　）。", "correct": "(0, 6)",
                      "wrongs": ["(0, -6)", "(6, 0)", "(-6, 0)"],
                      "l2": "y = x² + 6 的常数项是 6。",
                      "solution": "y = x² + 6 的顶点是 (0, 6)，选 {key}。"},
                 ])

    # F10 practice：y = x² - k 顶点纵坐标
    qs += family(g, "practice", 2,
                 "y = x² + k' 的顶点纵坐标是 k'。",
                 "类比：y = x² - 1 的顶点纵坐标是 -1。",
                 "顶点纵坐标就是常数项本身（注意符号）。",
                 [
                     {"prompt": "抛物线 y = x² - 3 的顶点纵坐标是多少？", "value": F(-3), "cfg": "integer",
                      "l2": "y = x² - 3 = x² + (-3)。",
                      "solution": "y = x² - 3 = x² + (-3)，顶点纵坐标为 {value}。"},
                     {"prompt": "抛物线 y = x² - 7 的顶点纵坐标是多少？", "value": F(-7), "cfg": "integer",
                      "l2": "y = x² - 7 = x² + (-7)。",
                      "solution": "y = x² - 7 = x² + (-7)，顶点纵坐标为 {value}。"},
                     {"prompt": "抛物线 y = x² - 9 的顶点纵坐标是多少？", "value": F(-9), "cfg": "integer",
                      "l2": "y = x² - 9 = x² + (-9)。",
                      "solution": "y = x² - 9 = x² + (-9)，顶点纵坐标为 {value}。"},
                 ])

    # F11 screening：顶点在原点的抛物线（mcq）
    qs += family(g, "screening", 1,
                 "抛物线是二次函数的图像；顶点在原点即 (0, 0)。",
                 "类比：y = x² 的顶点就是原点。",
                 "先排除一次函数，再找常数项为零的二次函数。",
                 [
                     {"prompt": "下列函数中，图像是抛物线且顶点在原点的是（　）。", "correct": "y = x²",
                      "wrongs": ["y = x² - 2", "y = 3x + 2", "y = -x² + 1"],
                      "l2": "y = ax² + k 的顶点在 (0, k)，k = 0 才在原点。",
                      "solution": "y = x² 无常数项、顶点 (0, 0)；其余或为一次函数或顶点不在原点。选 {key}。"},
                     {"prompt": "下列函数中，图像是抛物线且顶点在原点的是（　）。", "correct": "y = -x²",
                      "wrongs": ["y = -x² + 3", "y = 2x - 1", "y = x² + 4"],
                      "l2": "y = ax² + k 的顶点在 (0, k)，k = 0 才在原点。",
                      "solution": "y = -x² 无常数项、顶点 (0, 0)；其余或为一次函数或顶点不在原点。选 {key}。"},
                     {"prompt": "下列函数中，图像是抛物线且顶点在原点的是（　）。", "correct": "y = 3x²",
                      "wrongs": ["y = 3x² + 5", "y = 3x + 5", "y = -3x² + 5"],
                      "l2": "y = ax² + k 的顶点在 (0, k)，k = 0 才在原点。",
                      "solution": "y = 3x² 无常数项、顶点 (0, 0)；其余或为一次函数或顶点不在原点。选 {key}。"},
                 ])

    # F12 transfer：平移后的解析式（mcq）
    qs += family(g, "transfer", 2,
                 "上下平移改变每个点的纵坐标。",
                 "类比：括号里的加减是左右平移。",
                 "按方向确定常数项符号，再对照选项。",
                 [
                     {"prompt": "把抛物线 y = x² 向上平移 4 个单位，所得解析式是（　）。", "correct": "y = x² + 4",
                      "wrongs": ["y = x² - 4", "y = (x + 4)²", "y = (x - 4)²"],
                      "l2": "向上平移 k 个单位得 y = x² + k。",
                      "solution": "向上平移 4 个单位：每个 y 加 4，解析式为 y = x² + 4，选 {key}。"},
                     {"prompt": "把抛物线 y = x² 向下平移 2 个单位，所得解析式是（　）。", "correct": "y = x² - 2",
                      "wrongs": ["y = x² + 2", "y = (x + 2)²", "y = (x - 2)²"],
                      "l2": "向下平移 k 个单位得 y = x² - k。",
                      "solution": "向下平移 2 个单位：每个 y 减 2，解析式为 y = x² - 2，选 {key}。"},
                     {"prompt": "把抛物线 y = x² 向上平移 5 个单位，所得解析式是（　）。", "correct": "y = x² + 5",
                      "wrongs": ["y = x² - 5", "y = (x + 5)²", "y = (x - 5)²"],
                      "l2": "向上平移 k 个单位得 y = x² + k。",
                      "solution": "向上平移 5 个单位：每个 y 加 5，解析式为 y = x² + 5，选 {key}。"},
                 ])

    # F13 practice：对称性（给值求 -m）
    qs += family(g, "practice", 1,
                 "m 和 -m 关于 y 轴对称。",
                 "类比：x = 2 与 x = -2 时 y 都是 4。",
                 "x = -m 的函数值与 x = m 的完全相同。",
                 [
                     {"prompt": "已知 y = x²，当 x = 7 时 y = 49。当 x = -7 时，y = ？", "value": F(49), "cfg": "integer",
                      "l2": "7 与 -7 互为相反数，函数值相等。",
                      "solution": "(-7)² = 49；由对称性 x = -7 与 x = 7 的函数值相同，都是 {value}。"},
                     {"prompt": "已知 y = x²，当 x = 12 时 y = 144。当 x = -12 时，y = ？", "value": F(144), "cfg": "integer",
                      "l2": "12 与 -12 互为相反数，函数值相等。",
                      "solution": "(-12)² = 144；由对称性 x = -12 与 x = 12 的函数值相同，都是 {value}。"},
                     {"prompt": "已知 y = x²，当 x = 15 时 y = 225。当 x = -15 时，y = ？", "value": F(225), "cfg": "integer",
                      "l2": "15 与 -15 互为相反数，函数值相等。",
                      "solution": "(-15)² = 225；由对称性 x = -15 与 x = 15 的函数值相同，都是 {value}。"},
                 ])

    # F14 screening：图像上的点（小数）
    qs += family(g, "screening", 2,
                 "点在图像上，坐标满足方程。",
                 "类比：x = 0.3 时 y = 0.09。",
                 "小数乘法：先按整数乘，再点上小数点。",
                 [
                     {"prompt": "已知点 (1.5, y) 在抛物线 y = x² 上，求 y。（用小数作答）", "value": F(9) / 4, "cfg": "decimal",
                      "l2": "y = 1.5²，即 1.5×1.5。",
                      "solution": "y = 1.5×1.5 = {value}。"},
                     {"prompt": "已知点 (0.5, y) 在抛物线 y = x² 上，求 y。（用小数作答）", "value": F(1) / 4, "cfg": "decimal",
                      "l2": "y = 0.5²，即 0.5×0.5。",
                      "solution": "y = 0.5×0.5 = {value}。"},
                     {"prompt": "已知点 (2.5, y) 在抛物线 y = x² 上，求 y。（用小数作答）", "value": F(25) / 4, "cfg": "decimal",
                      "l2": "y = 2.5²，即 2.5×2.5。",
                      "solution": "y = 2.5×2.5 = {value}。"},
                 ])

    # F15 transfer：与 x 轴交点（mcq）
    qs += family(g, "transfer", 3,
                 "与 x 轴相交即 y = 0：解 x² = 给定的数。",
                 "类比：x² = 1 时交点是 (1, 0) 和 (-1, 0)。",
                 "交点纵坐标为 0，横坐标取两个互为相反数的值；对照选项。",
                 [
                     {"prompt": "抛物线 y = x² - 4 与 x 轴的交点坐标是（　）。", "correct": "(2, 0) 和 (-2, 0)",
                      "wrongs": ["(0, -4)", "(2, 0)", "没有交点"],
                      "l2": "令 y = 0：x² = 4。",
                      "solution": "x² = 4 得 x = ±2，交点为 (2, 0) 和 (-2, 0)，选 {key}。"},
                     {"prompt": "抛物线 y = x² - 9 与 x 轴的交点坐标是（　）。", "correct": "(3, 0) 和 (-3, 0)",
                      "wrongs": ["(0, -9)", "(3, 0)", "没有交点"],
                      "l2": "令 y = 0：x² = 9。",
                      "solution": "x² = 9 得 x = ±3，交点为 (3, 0) 和 (-3, 0)，选 {key}。"},
                     {"prompt": "抛物线 y = x² - 16 与 x 轴的交点坐标是（　）。", "correct": "(4, 0) 和 (-4, 0)",
                      "wrongs": ["(0, -16)", "(4, 0)", "没有交点"],
                      "l2": "令 y = 0：x² = 16。",
                      "solution": "x² = 16 得 x = ±4，交点为 (4, 0) 和 (-4, 0)，选 {key}。"},
                 ])

    # F16 practice：y = x² + k 顶点纵坐标
    qs += family(g, "practice", 1,
                 "y = x² + k 的顶点是 (0, k)。",
                 "类比：y = x² + 1 的顶点纵坐标是 1。",
                 "顶点纵坐标就是常数项，直接读出（注意符号）。",
                 [
                     {"prompt": "抛物线 y = x² + 4 的顶点纵坐标是多少？", "value": F(4), "cfg": "integer",
                      "l2": "常数项是 4。",
                      "solution": "y = x² + 4 的顶点是 (0, 4)，纵坐标为 {value}。"},
                     {"prompt": "抛物线 y = x² + 8 的顶点纵坐标是多少？", "value": F(8), "cfg": "integer",
                      "l2": "常数项是 8。",
                      "solution": "y = x² + 8 的顶点是 (0, 8)，纵坐标为 {value}。"},
                     {"prompt": "抛物线 y = x² + 6 的顶点纵坐标是多少？", "value": F(6), "cfg": "integer",
                      "l2": "常数项是 6。",
                      "solution": "y = x² + 6 的顶点是 (0, 6)，纵坐标为 {value}。"},
                 ])

    # F17 transfer：平移方向（mcq）
    qs += family(g, "transfer", 2,
                 "y = x² - k = x² + (-k)。",
                 "类比：y = x² + 2 是向上平移 2。",
                 "看常数项符号定方向，大小为它的绝对值；对照选项。",
                 [
                     {"prompt": "抛物线 y = x² - 3 是由 y = x² 怎样平移得到的？（　）", "correct": "向下平移 3 个单位",
                      "wrongs": ["向上平移 3 个单位", "向右平移 3 个单位", "向左平移 3 个单位"],
                      "l2": "常数项为负即向下平移。",
                      "solution": "y = x² - 3 的常数项为 -3 < 0，向下平移 3 个单位，选 {key}。"},
                     {"prompt": "抛物线 y = x² - 5 是由 y = x² 怎样平移得到的？（　）", "correct": "向下平移 5 个单位",
                      "wrongs": ["向上平移 5 个单位", "向右平移 5 个单位", "向左平移 5 个单位"],
                      "l2": "常数项为负即向下平移。",
                      "solution": "y = x² - 5 的常数项为 -5 < 0，向下平移 5 个单位，选 {key}。"},
                     {"prompt": "抛物线 y = x² - 1 是由 y = x² 怎样平移得到的？（　）", "correct": "向下平移 1 个单位",
                      "wrongs": ["向上平移 1 个单位", "向右平移 1 个单位", "向左平移 1 个单位"],
                      "l2": "常数项为负即向下平移。",
                      "solution": "y = x² - 1 的常数项为 -1 < 0，向下平移 1 个单位，选 {key}。"},
                 ])

    # F18 review：开口向下（mcq）
    qs += family(g, "review", 1,
                 "看二次项系数 a 的符号。",
                 "类比：y = -2x² 开口向下。",
                 "找系数带负号的那一项。",
                 [
                     {"prompt": "下列抛物线中，开口向下的是（　）。", "correct": "y = -x²",
                      "wrongs": ["y = x²", "y = 2x²", "y = x²/2"],
                      "l2": "a < 0 开口向下。",
                      "solution": "y = -x² 的 a = -1 < 0，开口向下，选 {key}。"},
                     {"prompt": "下列抛物线中，开口向下的是（　）。", "correct": "y = -3x²",
                      "wrongs": ["y = 3x²", "y = x²", "y = x²/3"],
                      "l2": "a < 0 开口向下。",
                      "solution": "y = -3x² 的 a = -3 < 0，开口向下，选 {key}。"},
                     {"prompt": "下列抛物线中，开口向下的是（　）。", "correct": "y = -x²/3",
                      "wrongs": ["y = x²/3", "y = 2x²", "y = x²"],
                      "l2": "a < 0 开口向下。",
                      "solution": "y = -x²/3 的 a = -1/3 < 0，开口向下，选 {key}。"},
                 ])

    # F19 practice：对称两点函数值之和
    qs += family(g, "practice", 2,
                 "对称性：互为相反数的两个 x，函数值相等。",
                 "类比：x = ±2 时 y 都是 4，和为 8。",
                 "先算出一个函数值，再加一次。",
                 [
                     {"prompt": "点 (3, y₁) 与 (-3, y₂) 在抛物线 y = x² 上，求 y₁ + y₂。", "value": F(18), "cfg": "integer",
                      "l2": "y₁ = y₂ = 9。",
                      "solution": "y₁ = y₂ = 3² = 9，y₁ + y₂ = {value}。"},
                     {"prompt": "点 (4, y₁) 与 (-4, y₂) 在抛物线 y = x² 上，求 y₁ + y₂。", "value": F(32), "cfg": "integer",
                      "l2": "y₁ = y₂ = 16。",
                      "solution": "y₁ = y₂ = 4² = 16，y₁ + y₂ = {value}。"},
                     {"prompt": "点 (6, y₁) 与 (-6, y₂) 在抛物线 y = x² 上，求 y₁ + y₂。", "value": F(72), "cfg": "integer",
                      "l2": "y₁ = y₂ = 36。",
                      "solution": "y₁ = y₂ = 6² = 36，y₁ + y₂ = {value}。"},
                 ])

    # F20 review：性质判断（mcq）
    qs += family(g, "review", 2,
                 "抓三条基本性质：最值、对称轴、取值范围。",
                 "类比：x = ±2 时 y 相等，说明图像关于 y 轴对称。",
                 "逐项对照三条基本性质，只有一项完全正确。",
                 [
                     {"prompt": "关于抛物线 y = x²，下列说法正确的是（　）。", "correct": "y 有最小值 0",
                      "wrongs": ["y 有最大值 0", "图像关于 x 轴对称", "y 随 x 增大而增大"],
                      "l2": "x² ≥ 0，且仅当 x = 0 时 y = 0。",
                      "solution": "y = x² 在顶点 (0,0) 处取得最小值 0；它没有最大值，关于 y 轴对称，且 x < 0 时 y 随 x 增大而减小。选 {key}。"},
                     {"prompt": "关于抛物线 y = x²，下列说法正确的是（　）。", "correct": "图像关于 y 轴对称",
                      "wrongs": ["y 有最大值 0", "图像关于 x 轴对称", "y 恒为正数"],
                      "l2": "互为相反数的 x 函数值相等。",
                      "solution": "(-x)² = x²，图像关于 y 轴对称；y = 0 时取到 0，不恒为正。选 {key}。"},
                     {"prompt": "关于抛物线 y = x²，下列说法正确的是（　）。", "correct": "y ≥ 0 恒成立",
                      "wrongs": ["y 有最大值 0", "图像关于 x 轴对称", "y 随 x 增大而增大"],
                      "l2": "任何数的平方都不小于 0。",
                      "solution": "x² ≥ 0 对一切 x 成立；无最大值，关于 y 轴对称，x < 0 时 y 随 x 增大而减小。选 {key}。"},
                 ])

    # F21 transfer：与 x 轴交点横坐标（取正）
    qs += family(g, "transfer", 3,
                 "与 x 轴相交即 y = 0：解 x² = 给定的数。",
                 "类比：x² = 16 时 x = 4。",
                 "想几乘几等于那个数；横坐标取正值。",
                 [
                     {"prompt": "抛物线 y = x² - 49 与 x 轴交点的横坐标（取正值）是多少？", "value": F(7), "cfg": "integer",
                      "l2": "令 y = 0：x² = 49。",
                      "solution": "x² = 49，取正值 x = {value}。"},
                     {"prompt": "抛物线 y = x² - 121 与 x 轴交点的横坐标（取正值）是多少？", "value": F(11), "cfg": "integer",
                      "l2": "令 y = 0：x² = 121。",
                      "solution": "x² = 121，取正值 x = {value}。"},
                     {"prompt": "抛物线 y = x² - 169 与 x 轴交点的横坐标（取正值）是多少？", "value": F(13), "cfg": "integer",
                      "l2": "令 y = 0：x² = 169。",
                      "solution": "x² = 169，取正值 x = {value}。"},
                 ])

    # F22 review：两点纵坐标差
    qs += family(g, "review", 3,
                 "分别算两点的纵坐标，再相减。",
                 "类比：a = 1 时 y₂ - y₁ = 9 - 1。",
                 "算出两个平方后相减，即为结果。",
                 [
                     {"prompt": "抛物线 y = x² 上有两点 (3, y₁) 和 (5, y₂)，求 y₂ - y₁。", "value": F(16), "cfg": "integer",
                      "l2": "y₁ = 9；y₂ = 25。",
                      "solution": "y₁ = 3² = 9，y₂ = 5² = 25，y₂ - y₁ = {value}。"},
                     {"prompt": "抛物线 y = x² 上有两点 (5, y₁) 和 (7, y₂)，求 y₂ - y₁。", "value": F(24), "cfg": "integer",
                      "l2": "y₁ = 25；y₂ = 49。",
                      "solution": "y₁ = 5² = 25，y₂ = 7² = 49，y₂ - y₁ = {value}。"},
                     {"prompt": "抛物线 y = x² 上有两点 (10, y₁) 和 (12, y₂)，求 y₂ - y₁。", "value": F(44), "cfg": "integer",
                      "l2": "y₁ = 100；y₂ = 144。",
                      "solution": "y₁ = 10² = 100，y₂ = 12² = 144，y₂ - y₁ = {value}。"},
                 ])

    return qs


# ---------------------------------------------------------------- C04 顶点式


def build_c04(g: Gen) -> list[dict]:
    qs: list[dict] = []

    # F9 screening：顶点（mcq）
    qs += family(g, "screening", 2,
                 "顶点式 y = a(x - h)² + k 的顶点是 (h, k)，注意 h 的符号。",
                 "类比：y = (x-1)²+2 的顶点是 (1, 2)。",
                 "k 取常数项；把 h 与 k 写成坐标后对照选项。",
                 [
                     {"prompt": "抛物线 y = (x - 2)² + 5 的顶点坐标是（　）。", "correct": "(2, 5)",
                      "wrongs": ["(-2, 5)", "(2, -5)", "(-2, -5)"],
                      "l2": "x - 2 = x - h，所以 h = 2；k = 5。",
                      "solution": "h = 2，k = 5，顶点为 (2, 5)，选 {key}。"},
                     {"prompt": "抛物线 y = (x - 6)² + 1 的顶点坐标是（　）。", "correct": "(6, 1)",
                      "wrongs": ["(-6, 1)", "(6, -1)", "(-6, -1)"],
                      "l2": "x - 6 = x - h，所以 h = 6；k = 1。",
                      "solution": "h = 6，k = 1，顶点为 (6, 1)，选 {key}。"},
                     {"prompt": "抛物线 y = (x - 4)² + 3 的顶点坐标是（　）。", "correct": "(4, 3)",
                      "wrongs": ["(-4, 3)", "(4, -3)", "(-4, -3)"],
                      "l2": "x - 4 = x - h，所以 h = 4；k = 3。",
                      "solution": "h = 4，k = 3，顶点为 (4, 3)，选 {key}。"},
                 ])

    # F10 screening：加号陷阱横坐标
    qs += family(g, "screening", 2,
                 "把 x + h 写成 x - (-h) 的形式再对照顶点式。",
                 "类比：y = (x+3)²-1 的顶点横坐标是 -3。",
                 "顶点横坐标取 +h 的相反数。",
                 [
                     {"prompt": "抛物线 y = (x + 6)² - 2 的顶点横坐标是多少？", "value": F(-6), "cfg": "integer",
                      "l2": "x + 6 = x - (-6)，所以 h = -6。",
                      "solution": "x + 6 = x - (-6)，顶点横坐标 h = {value}。"},
                     {"prompt": "抛物线 y = (x + 9)² - 4 的顶点横坐标是多少？", "value": F(-9), "cfg": "integer",
                      "l2": "x + 9 = x - (-9)，所以 h = -9。",
                      "solution": "x + 9 = x - (-9)，顶点横坐标 h = {value}。"},
                     {"prompt": "抛物线 y = (x + 12)² - 5 的顶点横坐标是多少？", "value": F(-12), "cfg": "integer",
                      "l2": "x + 12 = x - (-12)，所以 h = -12。",
                      "solution": "x + 12 = x - (-12)，顶点横坐标 h = {value}。"},
                 ])

    # F11 practice：a(x-h)²+k 顶点（mcq）
    qs += family(g, "practice", 2,
                 "系数 a 只影响开口，不影响顶点位置。",
                 "类比：y = 2(x-4)²+5 的顶点是 (4, 5)。",
                 "先去掉 a，读出 h 与 k，写成坐标后对照选项。",
                 [
                     {"prompt": "抛物线 y = 2(x - 3)² + 2 的顶点坐标是（　）。", "correct": "(3, 2)",
                      "wrongs": ["(-3, 2)", "(3, -2)", "(-3, -2)"],
                      "l2": "先不管 a = 2：h = 3，k = 2。",
                      "solution": "a = 2 不影响顶点；h = 3，k = 2，顶点为 (3, 2)，选 {key}。"},
                     {"prompt": "抛物线 y = 5(x - 1)² + 6 的顶点坐标是（　）。", "correct": "(1, 6)",
                      "wrongs": ["(-1, 6)", "(1, -6)", "(-1, -6)"],
                      "l2": "先不管 a = 5：h = 1，k = 6。",
                      "solution": "a = 5 不影响顶点；h = 1，k = 6，顶点为 (1, 6)，选 {key}。"},
                     {"prompt": "抛物线 y = -3(x - 5)² + 4 的顶点坐标是（　）。", "correct": "(5, 4)",
                      "wrongs": ["(-5, 4)", "(5, -4)", "(-5, -4)"],
                      "l2": "先不管 a = -3：h = 5，k = 4。",
                      "solution": "a = -3 只影响开口；h = 5，k = 4，顶点为 (5, 4)，选 {key}。"},
                 ])

    # F12 transfer：-a(x+h)²-k 顶点（mcq）
    qs += family(g, "transfer", 3,
                 "a 只影响开口，先去掉；再把括号化为 x - h 的形式。",
                 "类比：y = -2(x+3)²-1 的顶点是 (-3, -1)。",
                 "h 与 k 都取括号内数字和常数项的相反数，再对照选项。",
                 [
                     {"prompt": "抛物线 y = -4(x + 2)² - 3 的顶点坐标是（　）。", "correct": "(-2, -3)",
                      "wrongs": ["(2, -3)", "(-2, 3)", "(2, 3)"],
                      "l2": "x + 2 = x - (-2)，所以 h = -2；k = -3。",
                      "solution": "x + 2 = x - (-2)，k = -3，顶点为 (-2, -3)，选 {key}。"},
                     {"prompt": "抛物线 y = -5(x + 4)² - 2 的顶点坐标是（　）。", "correct": "(-4, -2)",
                      "wrongs": ["(4, -2)", "(-4, 2)", "(4, 2)"],
                      "l2": "x + 4 = x - (-4)，所以 h = -4；k = -2。",
                      "solution": "x + 4 = x - (-4)，k = -2，顶点为 (-4, -2)，选 {key}。"},
                     {"prompt": "抛物线 y = -3(x + 1)² - 5 的顶点坐标是（　）。", "correct": "(-1, -5)",
                      "wrongs": ["(1, -5)", "(-1, 5)", "(1, 5)"],
                      "l2": "x + 1 = x - (-1)，所以 h = -1；k = -5。",
                      "solution": "x + 1 = x - (-1)，k = -5，顶点为 (-1, -5)，选 {key}。"},
                 ])

    # F13 practice：顶点处取值
    qs += family(g, "practice", 1,
                 "x = h 时括号 x - h = 0，平方项为 0。",
                 "类比：y = 5(x-2)²+9 在 x = 2 时 y = 9。",
                 "y 就等于常数项 k。",
                 [
                     {"prompt": "已知 y = 3(x - 2)² + 5，当 x = 2 时，y = ？", "value": F(5), "cfg": "integer",
                      "l2": "x - 2 = 0，平方项为 0。",
                      "solution": "x = 2 时 y = 3×0 + 5 = {value}。"},
                     {"prompt": "已知 y = 4(x - 6)² + 1，当 x = 6 时，y = ？", "value": F(1), "cfg": "integer",
                      "l2": "x - 6 = 0，平方项为 0。",
                      "solution": "x = 6 时 y = 4×0 + 1 = {value}。"},
                     {"prompt": "已知 y = 2(x - 8)² + 7，当 x = 8 时，y = ？", "value": F(7), "cfg": "integer",
                      "l2": "x - 8 = 0，平方项为 0。",
                      "solution": "x = 8 时 y = 2×0 + 7 = {value}。"},
                 ])

    # F14 transfer：(h-x)²+k 顶点横坐标
    qs += family(g, "transfer", 3,
                 "相反数的平方相等：(h - x)² = (x - h)²。",
                 "类比：(6-x)² 的对称轴是 x = 6。",
                 "顶点横坐标等于对称轴，就是括号里那个常数。",
                 [
                     {"prompt": "抛物线 y = (7 - x)² + 1 的顶点横坐标是多少？", "value": F(7), "cfg": "integer",
                      "l2": "(7 - x)² = (x - 7)²。",
                      "solution": "(7 - x)² = (x - 7)²，顶点横坐标为 {value}。"},
                     {"prompt": "抛物线 y = (10 - x)² - 2 的顶点横坐标是多少？", "value": F(10), "cfg": "integer",
                      "l2": "(10 - x)² = (x - 10)²。",
                      "solution": "(10 - x)² = (x - 10)²，顶点横坐标为 {value}。"},
                     {"prompt": "抛物线 y = (15 - x)² + 4 的顶点横坐标是多少？", "value": F(15), "cfg": "integer",
                      "l2": "(15 - x)² = (x - 15)²。",
                      "solution": "(15 - x)² = (x - 15)²，顶点横坐标为 {value}。"},
                 ])

    # F15 review：a 的作用（mcq）
    qs += family(g, "review", 1,
                 "顶点 (h, k) 由括号与常数项决定，那 a 呢？",
                 "类比：y = 2(x-4)²+5 与 y = (x-4)²+5 的顶点相同。",
                 "对照选项：找只谈开口、不改变顶点的说法。",
                 [
                     {"prompt": "以 y = a(x - 3)² + 2 为例，系数 a 的作用是（　）。", "correct": "只影响开口方向与宽窄，不影响顶点位置",
                      "wrongs": ["决定顶点的横坐标", "决定顶点的纵坐标", "|a| 越大顶点越低"],
                      "l2": "顶点 (3, 2) 与 a 的取值无关。",
                      "solution": "a 只影响开口方向与宽窄；顶点 (3, 2) 由括号与常数项决定，选 {key}。"},
                     {"prompt": "以 y = a(x - 5)² + 1 为例，系数 a 的作用是（　）。", "correct": "只影响开口方向与宽窄，不影响顶点位置",
                      "wrongs": ["决定顶点的横坐标", "决定顶点的纵坐标", "|a| 越大顶点越低"],
                      "l2": "顶点 (5, 1) 与 a 的取值无关。",
                      "solution": "a 只影响开口方向与宽窄；顶点 (5, 1) 由括号与常数项决定，选 {key}。"},
                     {"prompt": "以 y = a(x - 4)² + 6 为例，系数 a 的作用是（　）。", "correct": "只影响开口方向与宽窄，不影响顶点位置",
                      "wrongs": ["决定顶点的横坐标", "决定顶点的纵坐标", "|a| 越大顶点越低"],
                      "l2": "顶点 (4, 6) 与 a 的取值无关。",
                      "solution": "a 只影响开口方向与宽窄；顶点 (4, 6) 由括号与常数项决定，选 {key}。"},
                 ])

    # F16 screening：(x+h)²+k 在 x=-h
    qs += family(g, "screening", 1,
                 "x = -h 时括号 x + h = 0，平方项为 0。",
                 "类比：y = 4(x+1)²+7 在 x = -1 时 y = 7。",
                 "y 就等于常数项 k。",
                 [
                     {"prompt": "已知 y = 5(x + 1)² + 3，当 x = -1 时，y = ？", "value": F(3), "cfg": "integer",
                      "l2": "x + 1 = 0，平方项为 0。",
                      "solution": "x = -1 时 y = 5×0 + 3 = {value}。"},
                     {"prompt": "已知 y = 2(x + 4)² + 6，当 x = -4 时，y = ？", "value": F(6), "cfg": "integer",
                      "l2": "x + 4 = 0，平方项为 0。",
                      "solution": "x = -4 时 y = 2×0 + 6 = {value}。"},
                     {"prompt": "已知 y = 3(x + 5)² + 2，当 x = -5 时，y = ？", "value": F(2), "cfg": "integer",
                      "l2": "x + 5 = 0，平方项为 0。",
                      "solution": "x = -5 时 y = 3×0 + 2 = {value}。"},
                 ])

    # F17 transfer：由顶点写解析式（mcq）
    qs += family(g, "transfer", 2,
                 "开口向上即 a > 0；顶点 (h, k) 对照 y = a(x - h)² + k。",
                 "类比：顶点 (1, 2) 且开口向上的是 y = (x-1)²+2。",
                 "把 h 与 k 的符号逐一核对再对照选项。",
                 [
                     {"prompt": "顶点为 (2, 3) 且开口向上的抛物线是（　）。", "correct": "y = (x - 2)² + 3",
                      "wrongs": ["y = (x + 2)² + 3", "y = (x - 2)² - 3", "y = -(x - 2)² + 3"],
                      "l2": "h = 2 对应 x - 2；k = 3。",
                      "solution": "开口向上取 a > 0；h = 2，k = 3，得 y = (x-2)²+3，选 {key}。"},
                     {"prompt": "顶点为 (-1, 4) 且开口向上的抛物线是（　）。", "correct": "y = (x + 1)² + 4",
                      "wrongs": ["y = (x - 1)² + 4", "y = (x + 1)² - 4", "y = -(x + 1)² + 4"],
                      "l2": "x - (-1) = x + 1；k = 4。",
                      "solution": "开口向上取 a > 0；h = -1 即括号为 x + 1，k = 4，选 {key}。"},
                     {"prompt": "顶点为 (3, -2) 且开口向上的抛物线是（　）。", "correct": "y = (x - 3)² - 2",
                      "wrongs": ["y = (x + 3)² - 2", "y = (x - 3)² + 2", "y = -(x - 3)² - 2"],
                      "l2": "h = 3 对应 x - 3；k = -2。",
                      "solution": "开口向上取 a > 0；h = 3，k = -2，得 y = (x-3)²-2，选 {key}。"},
                 ])

    # F18 practice：常数项为负的顶点纵坐标
    qs += family(g, "practice", 2,
                 "顶点纵坐标由常数项决定。",
                 "类比：y = 2(x-1)²+3 的顶点纵坐标是 3。",
                 "把常数项原样写出（它是负的），别变号。",
                 [
                     {"prompt": "抛物线 y = 2(x - 3)² - 2 的顶点纵坐标是多少？", "value": F(-2), "cfg": "integer",
                      "l2": "常数项是 -2。",
                      "solution": "顶点纵坐标等于常数项，为 {value}。"},
                     {"prompt": "抛物线 y = 4(x - 1)² - 5 的顶点纵坐标是多少？", "value": F(-5), "cfg": "integer",
                      "l2": "常数项是 -5。",
                      "solution": "顶点纵坐标等于常数项，为 {value}。"},
                     {"prompt": "抛物线 y = 5(x - 7)² - 9 的顶点纵坐标是多少？", "value": F(-9), "cfg": "integer",
                      "l2": "常数项是 -9。",
                      "solution": "顶点纵坐标等于常数项，为 {value}。"},
                 ])

    # F19 review：顶点在 x 轴上（mcq）
    qs += family(g, "review", 2,
                 "顶点在 x 轴上即纵坐标为 0。",
                 "类比：y = (x-2)² 的顶点 (2, 0) 在 x 轴上。",
                 "找没有常数项的那一项。",
                 [
                     {"prompt": "下列抛物线中，顶点在 x 轴上的是（　）。", "correct": "y = (x - 3)²",
                      "wrongs": ["y = (x - 3)² + 1", "y = (x + 3)² - 1", "y = (x - 3)² + 3"],
                      "l2": "顶点式里 k = 0 才在 x 轴上。",
                      "solution": "y = (x-3)² 的顶点 (3, 0) 在 x 轴上；其余顶点纵坐标非零。选 {key}。"},
                     {"prompt": "下列抛物线中，顶点在 x 轴上的是（　）。", "correct": "y = (x - 5)²",
                      "wrongs": ["y = (x - 5)² + 2", "y = (x + 5)² - 2", "y = (x - 5)² + 5"],
                      "l2": "顶点式里 k = 0 才在 x 轴上。",
                      "solution": "y = (x-5)² 的顶点 (5, 0) 在 x 轴上；其余顶点纵坐标非零。选 {key}。"},
                     {"prompt": "下列抛物线中，顶点在 x 轴上的是（　）。", "correct": "y = (x - 2)²",
                      "wrongs": ["y = (x - 2)² + 4", "y = (x + 2)² - 4", "y = (x - 2)² + 2"],
                      "l2": "顶点式里 k = 0 才在 x 轴上。",
                      "solution": "y = (x-2)² 的顶点 (2, 0) 在 x 轴上；其余顶点纵坐标非零。选 {key}。"},
                 ])

    # F20 practice：2(x-h)²+k 在 h+d
    qs += family(g, "practice", 2,
                 "先算括号差，再平方，最后乘 2 加 k。",
                 "类比：y = 2(x-1)²+3 在 x = 2 时是 2×1 + 3。",
                 "算出 2×平方 后加 k，即为 y。",
                 [
                     {"prompt": "已知 y = 2(x - 1)² + 3，当 x = 3 时，y = ？", "value": F(11), "cfg": "integer",
                      "l2": "x - 1 = 2，平方项是 4。",
                      "solution": "y = 2×2² + 3 = 2×4 + 3 = {value}。"},
                     {"prompt": "已知 y = 2(x - 3)² + 1，当 x = 6 时，y = ？", "value": F(19), "cfg": "integer",
                      "l2": "x - 3 = 3，平方项是 9。",
                      "solution": "y = 2×3² + 1 = 2×9 + 1 = {value}。"},
                     {"prompt": "已知 y = 2(x - 2)² + 5，当 x = 6 时，y = ？", "value": F(37), "cfg": "integer",
                      "l2": "x - 2 = 4，平方项是 16。",
                      "solution": "y = 2×4² + 5 = 2×16 + 5 = {value}。"},
                 ])

    # F21 transfer：顶点在 y 轴上（mcq）
    qs += family(g, "transfer", 2,
                 "顶点在 y 轴上即横坐标为 0。",
                 "类比：y = x² + 1 的顶点 (0, 1) 在 y 轴上。",
                 "找平方项只含 x、没有左右平移的那一项。",
                 [
                     {"prompt": "下列抛物线中，顶点在 y 轴上的是（　）。", "correct": "y = 3x² + 2",
                      "wrongs": ["y = 3(x - 2)²", "y = 3(x + 2)² + 2", "y = 3(x - 2)² + 2"],
                      "l2": "顶点式里 h = 0，即括号内只有 x。",
                      "solution": "y = 3x² + 2 的顶点 (0, 2) 在 y 轴上；其余顶点横坐标非零。选 {key}。"},
                     {"prompt": "下列抛物线中，顶点在 y 轴上的是（　）。", "correct": "y = 3x² - 1",
                      "wrongs": ["y = 3(x - 1)²", "y = 3(x + 1)² - 1", "y = 3(x - 1)² - 1"],
                      "l2": "顶点式里 h = 0，即括号内只有 x。",
                      "solution": "y = 3x² - 1 的顶点 (0, -1) 在 y 轴上；其余顶点横坐标非零。选 {key}。"},
                     {"prompt": "下列抛物线中，顶点在 y 轴上的是（　）。", "correct": "y = 3x² + 5",
                      "wrongs": ["y = 3(x - 5)²", "y = 3(x + 5)² + 5", "y = 3(x - 5)² + 5"],
                      "l2": "顶点式里 h = 0，即括号内只有 x。",
                      "solution": "y = 3x² + 5 的顶点 (0, 5) 在 y 轴上；其余顶点横坐标非零。选 {key}。"},
                 ])

    # F22 review：(x-h)²+k 在 h-d
    qs += family(g, "review", 3,
                 "x = h - d 时括号里是负数，平方后为正。",
                 "类比：y = 2(x-3)²+1 在 x = 2 时是 2×1 + 1。",
                 "算出 a×平方 后加 k，即为 y。",
                 [
                     {"prompt": "已知 y = 2(x - 3)² + 1，当 x = 1 时，y = ？", "value": F(9), "cfg": "integer",
                      "l2": "x - 3 = -2，平方项是 4。",
                      "solution": "y = 2×(-2)² + 1 = 8 + 1 = {value}。"},
                     {"prompt": "已知 y = 3(x - 1)² + 2，当 x = -2 时，y = ？", "value": F(29), "cfg": "integer",
                      "l2": "x - 1 = -3，平方项是 9。",
                      "solution": "y = 3×(-3)² + 2 = 27 + 2 = {value}。"},
                     {"prompt": "已知 y = (x - 5)² + 3，当 x = 1 时，y = ？", "value": F(19), "cfg": "integer",
                      "l2": "x - 5 = -4，平方项是 16。",
                      "solution": "y = (-4)² + 3 = 16 + 3 = {value}。"},
                 ])

    return qs


# ---------------------------------------------------------------- C05 开口与对称轴


def build_c05(g: Gen) -> list[dict]:
    qs: list[dict] = []

    # F9 screening：开口方向（mcq）
    qs += family(g, "screening", 1,
                 "看二次项系数 a 的符号。",
                 "类比：y = -2x² 开口向下。",
                 "按 a 的符号判断方向后对照选项。",
                 [
                     {"prompt": "抛物线 y = 9x² 的开口方向是（　）。", "correct": "向上",
                      "wrongs": ["向下", "向左", "向右"],
                      "l2": "a = 9 > 0。",
                      "solution": "a = 9 > 0，开口向上，选 {key}。"},
                     {"prompt": "抛物线 y = -7x² 的开口方向是（　）。", "correct": "向下",
                      "wrongs": ["向上", "向左", "向右"],
                      "l2": "a = -7 < 0。",
                      "solution": "a = -7 < 0，开口向下，选 {key}。"},
                     {"prompt": "抛物线 y = -12x² 的开口方向是（　）。", "correct": "向下",
                      "wrongs": ["向上", "向左", "向右"],
                      "l2": "a = -12 < 0。",
                      "solution": "a = -12 < 0，开口向下，选 {key}。"},
                 ])

    # F10 practice：对称轴
    qs += family(g, "practice", 1,
                 "顶点式 y = a(x - h)² + k 的对称轴是 x = h。",
                 "类比：y = (x-5)² 的对称轴是 x = 5。",
                 "对称轴 x = h，直接读括号里的数。",
                 [
                     {"prompt": "抛物线 y = (x - 8)² 的对称轴是 x = ？", "value": F(8), "cfg": "integer",
                      "l2": "对照 x - h：h = 8。",
                      "solution": "y = (x-8)² 的对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = (x - 14)² 的对称轴是 x = ？", "value": F(14), "cfg": "integer",
                      "l2": "对照 x - h：h = 14。",
                      "solution": "y = (x-14)² 的对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = (x - 20)² 的对称轴是 x = ？", "value": F(20), "cfg": "integer",
                      "l2": "对照 x - h：h = 20。",
                      "solution": "y = (x-20)² 的对称轴为 x = {value}。"},
                 ])

    # F11 screening：加号陷阱对称轴
    qs += family(g, "screening", 2,
                 "把 x + h 写成 x - (-h) 再读对称轴。",
                 "类比：y = (x+2)² 的对称轴是 x = -2。",
                 "别忘变号：+h 的对称轴是负的。",
                 [
                     {"prompt": "抛物线 y = 2(x + 6)² 的对称轴是 x = ？", "value": F(-6), "cfg": "integer",
                      "l2": "x + 6 = x - (-6)。",
                      "solution": "x + 6 = x - (-6)，对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = 5(x + 13)² - 1 的对称轴是 x = ？", "value": F(-13), "cfg": "integer",
                      "l2": "x + 13 = x - (-13)。",
                      "solution": "x + 13 = x - (-13)，对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = (x + 17)² + 3 的对称轴是 x = ？", "value": F(-17), "cfg": "integer",
                      "l2": "x + 17 = x - (-17)。",
                      "solution": "x + 17 = x - (-17)，对称轴为 x = {value}。"},
                 ])

    # F12 transfer：开口最宽（mcq）
    qs += family(g, "transfer", 2,
                 "|a| 越小，开口越宽；比较各选项 |a| 的大小。",
                 "类比：y = x²/2 比 y = x² 宽。",
                 "把各选项系数取绝对值比较，找最小的一项。",
                 [
                     {"prompt": "下列抛物线中，开口最宽的是（　）。", "correct": "y = x²/5",
                      "wrongs": ["y = x²", "y = 2x²", "y = 3x²"],
                      "l2": "|a| 依次为 1/5、1、2、3。",
                      "solution": "|a| 越小越宽：1/5 最小，故 y = x²/5 开口最宽，选 {key}。"},
                     {"prompt": "下列抛物线中，开口最宽的是（　）。", "correct": "y = x²/3",
                      "wrongs": ["y = x²", "y = 2x²", "y = 5x²"],
                      "l2": "|a| 依次为 1/3、1、2、5。",
                      "solution": "|a| 越小越宽：1/3 最小，故 y = x²/3 开口最宽，选 {key}。"},
                     {"prompt": "下列抛物线中，开口最宽的是（　）。", "correct": "y = x²/2",
                      "wrongs": ["y = x²", "y = 3x²", "y = 4x²"],
                      "l2": "|a| 依次为 1/2、1、3、4。",
                      "solution": "|a| 越小越宽：1/2 最小，故 y = x²/2 开口最宽，选 {key}。"},
                 ])

    # F13 transfer：相同对称轴（mcq）
    qs += family(g, "transfer", 2,
                 "对称轴只由括号里的 h 决定。",
                 "类比：y = 2(x+3)²-1 与 y = (x+3)² 的对称轴相同。",
                 "逐项写出各选项的对称轴再对照。",
                 [
                     {"prompt": "与抛物线 y = 2(x + 3)² - 1 对称轴相同的是（　）。", "correct": "y = (x + 3)²",
                      "wrongs": ["y = (x - 3)²", "y = 2(x + 1)²", "y = 2(x - 1)²"],
                      "l2": "该抛物线的对称轴是 x = -3。",
                      "solution": "y = 2(x+3)²-1 的对称轴是 x = -3；选项中只有 y = (x+3)² 相同，选 {key}。"},
                     {"prompt": "与抛物线 y = 2(x + 5)² - 2 对称轴相同的是（　）。", "correct": "y = (x + 5)²",
                      "wrongs": ["y = (x - 5)²", "y = 2(x + 2)²", "y = 2(x - 2)²"],
                      "l2": "该抛物线的对称轴是 x = -5。",
                      "solution": "y = 2(x+5)²-2 的对称轴是 x = -5；选项中只有 y = (x+5)² 相同，选 {key}。"},
                     {"prompt": "与抛物线 y = 2(x + 4)² - 6 对称轴相同的是（　）。", "correct": "y = (x + 4)²",
                      "wrongs": ["y = (x - 4)²", "y = 2(x + 6)²", "y = 2(x - 6)²"],
                      "l2": "该抛物线的对称轴是 x = -4。",
                      "solution": "y = 2(x+4)²-6 的对称轴是 x = -4；选项中只有 y = (x+4)² 相同，选 {key}。"},
                 ])

    # F14 review：(h-x)² 对称轴
    qs += family(g, "review", 2,
                 "相反数的平方相等：(h - x)² = (x - h)²。",
                 "类比：(3-x)² = (x-3)²。",
                 "对称轴取正的那个常数。",
                 [
                     {"prompt": "抛物线 y = (11 - x)² 的对称轴是 x = ？", "value": F(11), "cfg": "integer",
                      "l2": "(11 - x)² = (x - 11)²。",
                      "solution": "(11 - x)² = (x - 11)²，对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = (14 - x)² 的对称轴是 x = ？", "value": F(14), "cfg": "integer",
                      "l2": "(14 - x)² = (x - 14)²。",
                      "solution": "(14 - x)² = (x - 14)²，对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = (18 - x)² 的对称轴是 x = ？", "value": F(18), "cfg": "integer",
                      "l2": "(18 - x)² = (x - 18)²。",
                      "solution": "(18 - x)² = (x - 18)²，对称轴为 x = {value}。"},
                 ])

    # F15 transfer：开口 + 对称轴组合（mcq）
    qs += family(g, "transfer", 2,
                 "分别判断 a 的符号与 h。",
                 "类比：y = -2(x-3)² 开口向下、对称轴 x = 3。",
                 "符号与位置分开判断，再对照选项。",
                 [
                     {"prompt": "抛物线 y = -5(x - 2)² 的开口方向与对称轴是（　）。", "correct": "开口向下，对称轴 x = 2",
                      "wrongs": ["开口向上，对称轴 x = 2", "开口向下，对称轴 x = -2", "开口向上，对称轴 x = -2"],
                      "l2": "a = -5 < 0；括号是 x - 2。",
                      "solution": "a = -5 < 0 开口向下；对称轴 x = 2，选 {key}。"},
                     {"prompt": "抛物线 y = -3(x - 6)² 的开口方向与对称轴是（　）。", "correct": "开口向下，对称轴 x = 6",
                      "wrongs": ["开口向上，对称轴 x = 6", "开口向下，对称轴 x = -6", "开口向上，对称轴 x = -6"],
                      "l2": "a = -3 < 0；括号是 x - 6。",
                      "solution": "a = -3 < 0 开口向下；对称轴 x = 6，选 {key}。"},
                     {"prompt": "抛物线 y = -8(x - 1)² 的开口方向与对称轴是（　）。", "correct": "开口向下，对称轴 x = 1",
                      "wrongs": ["开口向上，对称轴 x = 1", "开口向下，对称轴 x = -1", "开口向上，对称轴 x = -1"],
                      "l2": "a = -8 < 0；括号是 x - 1。",
                      "solution": "a = -8 < 0 开口向下；对称轴 x = 1，选 {key}。"},
                 ])

    # F16 screening：开口向上（mcq）
    qs += family(g, "screening", 1,
                 "看各选项二次项系数的符号。",
                 "类比：y = x² 开口向上。",
                 "找系数为正的那一项。",
                 [
                     {"prompt": "下列抛物线中，开口向上的是（　）。", "correct": "y = x²",
                      "wrongs": ["y = -x²", "y = -2x²", "y = -x²/2"],
                      "l2": "只有 a > 0 才开口向上。",
                      "solution": "y = x² 的 a = 1 > 0，开口向上，选 {key}。"},
                     {"prompt": "下列抛物线中，开口向上的是（　）。", "correct": "y = 3x²",
                      "wrongs": ["y = -3x²", "y = -x²", "y = -x²/3"],
                      "l2": "只有 a > 0 才开口向上。",
                      "solution": "y = 3x² 的 a = 3 > 0，开口向上，选 {key}。"},
                     {"prompt": "下列抛物线中，开口向上的是（　）。", "correct": "y = x²/4",
                      "wrongs": ["y = -x²/4", "y = -4x²", "y = -x²"],
                      "l2": "只有 a > 0 才开口向上。",
                      "solution": "y = x²/4 的 a = 1/4 > 0，开口向上，选 {key}。"},
                 ])

    # F17 practice：对称轴（带 a、k）
    qs += family(g, "practice", 1,
                 "对称轴只与括号里的 h 有关。",
                 "类比：y = 2(x-5)²+1 的对称轴是 x = 5。",
                 "a 与 k 都不影响对称轴。",
                 [
                     {"prompt": "抛物线 y = 7(x - 3)² + 2 的对称轴是 x = ？", "value": F(3), "cfg": "integer",
                      "l2": "对照 x - h：h = 3。",
                      "solution": "对称轴为 x = {value}（a、k 不影响）。"},
                     {"prompt": "抛物线 y = 2(x - 9)² + 4 的对称轴是 x = ？", "value": F(9), "cfg": "integer",
                      "l2": "对照 x - h：h = 9。",
                      "solution": "对称轴为 x = {value}（a、k 不影响）。"},
                     {"prompt": "抛物线 y = 6(x - 12)² + 1 的对称轴是 x = ？", "value": F(12), "cfg": "integer",
                      "l2": "对照 x - h：h = 12。",
                      "solution": "对称轴为 x = {value}（a、k 不影响）。"},
                 ])

    # F18 transfer：(kx - c)² 对称轴
    qs += family(g, "transfer", 3,
                 "先提出括号里的公因数。",
                 "类比：(2x-4)² = 4(x-2)²，对称轴 x = 2。",
                 "令括号等于零解出 x，即为对称轴。",
                 [
                     {"prompt": "抛物线 y = (2x - 6)² 的对称轴是 x = ？（提示：提出括号里的系数）", "value": F(3), "cfg": "integer",
                      "l2": "(2x - 6)² = 4(x - 3)²。",
                      "solution": "(2x-6)² = 4(x-3)²，对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = (3x - 12)² 的对称轴是 x = ？（提示：提出括号里的系数）", "value": F(4), "cfg": "integer",
                      "l2": "(3x - 12)² = 9(x - 4)²。",
                      "solution": "(3x-12)² = 9(x-4)²，对称轴为 x = {value}。"},
                     {"prompt": "抛物线 y = (2x - 10)² 的对称轴是 x = ？（提示：提出括号里的系数）", "value": F(5), "cfg": "integer",
                      "l2": "(2x - 10)² = 4(x - 5)²。",
                      "solution": "(2x-10)² = 4(x-5)²，对称轴为 x = {value}。"},
                 ])

    # F19 practice：由对称轴反求 h
    qs += family(g, "practice", 2,
                 "顶点式 y = a(x + h)² + k 的对称轴是 x = -h。",
                 "类比：对称轴 x = -1 时 h = 1。",
                 "变号即可，注意负号。",
                 [
                     {"prompt": "抛物线 y = 3(x + h)² + 1 的对称轴是 x = -4，则 h = ？", "value": F(4), "cfg": "integer",
                      "l2": "-h 就是给出的对称轴，h 取相反数。",
                      "solution": "对称轴 x = -h = -4，所以 h = {value}。"},
                     {"prompt": "抛物线 y = 3(x + h)² + 1 的对称轴是 x = -9，则 h = ？", "value": F(9), "cfg": "integer",
                      "l2": "-h 就是给出的对称轴，h 取相反数。",
                      "solution": "对称轴 x = -h = -9，所以 h = {value}。"},
                     {"prompt": "抛物线 y = 3(x + h)² + 1 的对称轴是 x = -2，则 h = ？", "value": F(2), "cfg": "integer",
                      "l2": "-h 就是给出的对称轴，h 取相反数。",
                      "solution": "对称轴 x = -h = -2，所以 h = {value}。"},
                 ])

    # F20 review：错误说法（mcq）
    qs += family(g, "review", 2,
                 "逐项回想开口、宽窄、对称轴的结论。",
                 "类比：y = 3x² 比 y = x² 窄，各自对称轴都过自己的顶点。",
                 "找与基本结论矛盾的那一项。",
                 [
                     {"prompt": "下列说法错误的是（　）。", "correct": "a < 0 时开口向上",
                      "wrongs": ["a > 0 时开口向上", "|a| 越大开口越窄", "对称轴经过抛物线的顶点"],
                      "l2": "a < 0 开口向下。",
                      "solution": "a < 0 开口向下（说法错误）；其余三条均为正确结论。选 {key}。"},
                     {"prompt": "下列说法错误的是（　）。", "correct": "|a| 越小开口越窄",
                      "wrongs": ["a < 0 时开口向下", "|a| 越大开口越窄", "对称轴经过抛物线的顶点"],
                      "l2": "|a| 越小开口越宽。",
                      "solution": "|a| 越小开口越宽（说法错误）；其余三条均为正确结论。选 {key}。"},
                     {"prompt": "下列说法错误的是（　）。", "correct": "对称轴平行于 x 轴",
                      "wrongs": ["a < 0 时开口向下", "|a| 越大开口越窄", "对称轴经过抛物线的顶点"],
                      "l2": "y = a(x-h)²+k 的对称轴是直线 x = h，垂直于 x 轴。",
                      "solution": "对称轴 x = h 是垂直于 x 轴的直线（说法错误）；其余三条均为正确结论。选 {key}。"},
                 ])

    # F21 practice：对称等距点函数值（mcq）
    qs += family(g, "practice", 2,
                 "两点与对称轴的距离是多少？",
                 "类比：y = x² 中 x = ±3 时 y 相等。",
                 "算出两点横坐标与 h 的差的绝对值，再比较。",
                 [
                     {"prompt": "抛物线 y = (x - 3)² 上，x = 1 与 x = 5 两点的函数值（　）。", "correct": "相等",
                      "wrongs": ["x = 5 时更大", "x = 1 时更大", "无法比较"],
                      "l2": "两点到对称轴 x = 3 的距离都是 2。",
                      "solution": "1 和 5 到对称轴 x = 3 等距，函数值相等（都是 4），选 {key}。"},
                     {"prompt": "抛物线 y = (x - 4)² 上，x = 3 与 x = 5 两点的函数值（　）。", "correct": "相等",
                      "wrongs": ["x = 5 时更大", "x = 3 时更大", "无法比较"],
                      "l2": "两点到对称轴 x = 4 的距离都是 1。",
                      "solution": "3 和 5 到对称轴 x = 4 等距，函数值相等（都是 1），选 {key}。"},
                     {"prompt": "抛物线 y = (x - 6)² 上，x = 3 与 x = 9 两点的函数值（　）。", "correct": "相等",
                      "wrongs": ["x = 9 时更大", "x = 3 时更大", "无法比较"],
                      "l2": "两点到对称轴 x = 6 的距离都是 3。",
                      "solution": "3 和 9 到对称轴 x = 6 等距，函数值相等（都是 9），选 {key}。"},
                 ])

    # F22 review：x = 0 处的函数值
    qs += family(g, "review", 3,
                 "代入 x = 0：y = (0 - h)² + k。",
                 "类比：y = (x-1)²+2 在 x = 0 时是 1 + 2。",
                 "算出 h² 后加 k，即为 y。",
                 [
                     {"prompt": "抛物线 y = (x - 2)² + 1 的对称轴是 x = 2。当 x = 0 时，y = ？", "value": F(5), "cfg": "integer",
                      "l2": "(0 - 2)² = 4。",
                      "solution": "y = (0-2)² + 1 = 4 + 1 = {value}。"},
                     {"prompt": "抛物线 y = (x - 3)² + 2 的对称轴是 x = 3。当 x = 0 时，y = ？", "value": F(11), "cfg": "integer",
                      "l2": "(0 - 3)² = 9。",
                      "solution": "y = (0-3)² + 2 = 9 + 2 = {value}。"},
                     {"prompt": "抛物线 y = (x - 4)² + 1 的对称轴是 x = 4。当 x = 0 时，y = ？", "value": F(17), "cfg": "integer",
                      "l2": "(0 - 4)² = 16。",
                      "solution": "y = (0-4)² + 1 = 16 + 1 = {value}。"},
                 ])

    return qs


# ---------------------------------------------------------------- C06 简单应用


def build_c06(g: Gen) -> list[dict]:
    qs: list[dict] = []

    # F9 screening：落体代入（mcq）
    qs += family(g, "screening", 2,
                 "把 t 代入 h = H - 5t²，先算 t²。",
                 "类比：h = 20 - 5t² 在 t = 1 时是 20 - 5。",
                 "再用 H 减去它，与选项对照（单位：米）。",
                 [
                     {"prompt": "小球从 30 米高处下落，离地高度 h = 30 - 5t²（米）。当 t = 2 秒时，h = ？",
                      "correct": "10 米", "wrongs": ["20 米", "50 米", "26 米"],
                      "l2": "t² = 4，5t² = 20。",
                      "solution": "h = 30 - 5×2² = 30 - 20 = 10（米），选 {key}。"},
                     {"prompt": "小球从 60 米高处下落，离地高度 h = 60 - 5t²（米）。当 t = 2 秒时，h = ？",
                      "correct": "40 米", "wrongs": ["50 米", "80 米", "56 米"],
                      "l2": "t² = 4，5t² = 20。",
                      "solution": "h = 60 - 5×2² = 60 - 20 = 40（米），选 {key}。"},
                     {"prompt": "小球从 80 米高处下落，离地高度 h = 80 - 5t²（米）。当 t = 3 秒时，h = ？",
                      "correct": "35 米", "wrongs": ["65 米", "125 米", "71 米"],
                      "l2": "t² = 9，5t² = 45。",
                      "solution": "h = 80 - 5×3² = 80 - 45 = 35（米），选 {key}。"},
                 ])

    # F10 practice：正方形面积
    qs += family(g, "practice", 1,
                 "面积 = 边长²。",
                 "类比：边长 7 时面积 49。",
                 "直接计算边长×边长，结果即为面积。",
                 [
                     {"prompt": "正方形边长为 9 米，面积是多少平方米？", "value": F(81), "cfg": "integer",
                      "l2": "面积 = 9×9。",
                      "solution": "面积 = 9×9 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 15 米，面积是多少平方米？", "value": F(225), "cfg": "integer",
                      "l2": "面积 = 15×15。",
                      "solution": "面积 = 15×15 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 24 米，面积是多少平方米？", "value": F(576), "cfg": "integer",
                      "l2": "面积 = 24×24。",
                      "solution": "面积 = 24×24 = {value}（平方米）。"},
                 ])

    # F11 practice：边长增加后的面积
    qs += family(g, "practice", 2,
                 "新边长是 x + d，先求出来。",
                 "类比：x=3, d=2 时新边长 5，面积 25。",
                 "把新边长自乘，即为新面积。",
                 [
                     {"prompt": "正方形边长增加 3 后为 x + 3，面积 y = (x + 3)²。当 x = 4 时，新面积是多少？",
                      "value": F(49), "cfg": "integer",
                      "l2": "新边长 = 4 + 3 = 7。",
                      "solution": "新边长 7，面积 = 7² = {value}。"},
                     {"prompt": "正方形边长增加 2 后为 x + 2，面积 y = (x + 2)²。当 x = 6 时，新面积是多少？",
                      "value": F(64), "cfg": "integer",
                      "l2": "新边长 = 6 + 2 = 8。",
                      "solution": "新边长 8，面积 = 8² = {value}。"},
                     {"prompt": "正方形边长增加 5 后为 x + 5，面积 y = (x + 5)²。当 x = 5 时，新面积是多少？",
                      "value": F(100), "cfg": "integer",
                      "l2": "新边长 = 5 + 5 = 10。",
                      "solution": "新边长 10，面积 = 10² = {value}。"},
                 ])

    # F12 review：落地时刻
    qs += family(g, "review", 3,
                 "落地即 h = 0：解方程 H - 5t² = 0。",
                 "类比：t² = 9 时 t = 3（取正）。",
                 "开平方取正值，即为落地时间。",
                 [
                     {"prompt": "小球离地高度 h = 80 - 5t²（米）。小球落地（h = 0）时 t = ？秒（取正值）。",
                      "value": F(4), "cfg": "integer",
                      "l2": "5t² = 80，t² = 16。",
                      "solution": "80 - 5t² = 0 得 t² = 16，取正值 t = {value} 秒。"},
                     {"prompt": "小球离地高度 h = 180 - 5t²（米）。小球落地（h = 0）时 t = ？秒（取正值）。",
                      "value": F(6), "cfg": "integer",
                      "l2": "5t² = 180，t² = 36。",
                      "solution": "180 - 5t² = 0 得 t² = 36，取正值 t = {value} 秒。"},
                     {"prompt": "小球离地高度 h = 245 - 5t²（米）。小球落地（h = 0）时 t = ？秒（取正值）。",
                      "value": F(7), "cfg": "integer",
                      "l2": "5t² = 245，t² = 49。",
                      "solution": "245 - 5t² = 0 得 t² = 49，取正值 t = {value} 秒。"},
                 ])

    # F13 transfer：逆解 (x+d)² = K
    qs += family(g, "transfer", 3,
                 "逆向思考：什么数的平方等于给定的面积？",
                 "类比：(x+2)² = 49 时 x + 2 = 7。",
                 "求出 x + d 后再减 d，即为 x。",
                 [
                     {"prompt": "正方形边长增加 2 后为 x + 2，面积 y = (x + 2)²。若新面积为 25 平方米且 x > 0，则 x = ？",
                      "value": F(3), "cfg": "integer",
                      "l2": "(x + 2)² = 25，x + 2 = 5（取正）。",
                      "solution": "x + 2 = 5，x = {value}。"},
                     {"prompt": "正方形边长增加 3 后为 x + 3，面积 y = (x + 3)²。若新面积为 64 平方米且 x > 0，则 x = ？",
                      "value": F(5), "cfg": "integer",
                      "l2": "(x + 3)² = 64，x + 3 = 8（取正）。",
                      "solution": "x + 3 = 8，x = {value}。"},
                     {"prompt": "正方形边长增加 1 后为 x + 1，面积 y = (x + 1)²。若新面积为 36 平方米且 x > 0，则 x = ？",
                      "value": F(5), "cfg": "integer",
                      "l2": "(x + 1)² = 36，x + 1 = 6（取正）。",
                      "solution": "x + 1 = 6，x = {value}。"},
                 ])

    # F14 transfer：面积增加量
    qs += family(g, "transfer", 3,
                 "分别算新面积 (x+d)² 与原面积 x²，再相减。",
                 "类比：x=1, d=1 时增加 4 - 1 = 3。",
                 "两个平方相减，即为增加量。",
                 [
                     {"prompt": "正方形边长为 10 米，边长增加 2 米后，面积增加了多少平方米？",
                      "value": F(44), "cfg": "integer",
                      "l2": "新边长 12，新面积 144；原面积 100。",
                      "solution": "12² - 10² = 144 - 100 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 6 米，边长增加 4 米后，面积增加了多少平方米？",
                      "value": F(64), "cfg": "integer",
                      "l2": "新边长 10，新面积 100；原面积 36。",
                      "solution": "10² - 6² = 100 - 36 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 8 米，边长增加 3 米后，面积增加了多少平方米？",
                      "value": F(57), "cfg": "integer",
                      "l2": "新边长 11，新面积 121；原面积 64。",
                      "solution": "11² - 8² = 121 - 64 = {value}（平方米）。"},
                 ])

    # F15 screening：小数边长面积
    qs += family(g, "screening", 2,
                 "面积 = 边长²，即 d×d。",
                 "类比：边长 0.5 时面积 0.25。",
                 "先按整数乘，再点上小数点（结果用小数表示）。",
                 [
                     {"prompt": "正方形边长为 0.3 米，面积是多少平方米？（用小数作答）", "value": F(9) / 100, "cfg": "decimal",
                      "l2": "面积 = 0.3×0.3，两个因数共两位小数。",
                      "solution": "面积 = 0.3×0.3 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 2.5 米，面积是多少平方米？（用小数作答）", "value": F(25) / 4, "cfg": "decimal",
                      "l2": "面积 = 2.5×2.5，两个因数共两位小数。",
                      "solution": "面积 = 2.5×2.5 = {value}（平方米）。"},
                     {"prompt": "正方形边长为 1.2 米，面积是多少平方米？（用小数作答）", "value": F(36) / 25, "cfg": "decimal",
                      "l2": "面积 = 1.2×1.2，两个因数共两位小数。",
                      "solution": "面积 = 1.2×1.2 = {value}（平方米）。"},
                 ])

    # F16 transfer：挖去小正方形
    qs += family(g, "transfer", 2,
                 "剩余面积 = 大正方形面积 - 小正方形面积。",
                 "类比：x=5, d=2 时是 25 - 4。",
                 "两个平方相减，即为剩余面积。",
                 [
                     {"prompt": "从边长 9 米的大正方形纸板上，挖去一个边长 4 米的小正方形，剩余面积是多少平方米？",
                      "value": F(65), "cfg": "integer",
                      "l2": "大面积 = 81；小面积 = 16。",
                      "solution": "9² - 4² = 81 - 16 = {value}（平方米）。"},
                     {"prompt": "从边长 12 米的大正方形纸板上，挖去一个边长 6 米的小正方形，剩余面积是多少平方米？",
                      "value": F(108), "cfg": "integer",
                      "l2": "大面积 = 144；小面积 = 36。",
                      "solution": "12² - 6² = 144 - 36 = {value}（平方米）。"},
                     {"prompt": "从边长 10 米的大正方形纸板上，挖去一个边长 8 米的小正方形，剩余面积是多少平方米？",
                      "value": F(36), "cfg": "integer",
                      "l2": "大面积 = 100；小面积 = 64。",
                      "solution": "10² - 8² = 100 - 64 = {value}（平方米）。"},
                 ])

    # F17 review：负时间根的处理（mcq）
    qs += family(g, "review", 1,
                 "时间、长度这些实际的量能取负吗？",
                 "类比：t² = 9 时 t = 3（取正）。",
                 "负根舍去，取对应的正值。",
                 [
                     {"prompt": "解方程 20 - 5t² = 0 得 t² = 4，求小球落地时刻（　）。",
                      "correct": "时间取正值，t = 2 秒",
                      "wrongs": ["直接用 t = -2 秒", "方程无解", "t = 2 或 t = -2 都正确"],
                      "l2": "t² = 4 的根有 2 和 -2。",
                      "solution": "t² = 4 的根为 ±2，时间取正值 t = 2 秒，选 {key}。"},
                     {"prompt": "解方程 45 - 5t² = 0 得 t² = 9，求小球落地时刻（　）。",
                      "correct": "时间取正值，t = 3 秒",
                      "wrongs": ["直接用 t = -3 秒", "方程无解", "t = 3 或 t = -3 都正确"],
                      "l2": "t² = 9 的根有 3 和 -3。",
                      "solution": "t² = 9 的根为 ±3，时间取正值 t = 3 秒，选 {key}。"},
                     {"prompt": "解方程 125 - 5t² = 0 得 t² = 25，求小球落地时刻（　）。",
                      "correct": "时间取正值，t = 5 秒",
                      "wrongs": ["直接用 t = -5 秒", "方程无解", "t = 5 或 t = -5 都正确"],
                      "l2": "t² = 25 的根有 5 和 -5。",
                      "solution": "t² = 25 的根为 ±5，时间取正值 t = 5 秒，选 {key}。"},
                 ])

    # F18 practice：指定高度的时刻
    qs += family(g, "practice", 2,
                 "代入求 t：H - 5t² = 给定高度。",
                 "类比：20 - 5t² = 15 时 t² = 1，t = 1。",
                 "移项求出 t²，再开平方取正值。",
                 [
                     {"prompt": "小球离地高度 h = 100 - 5t²（米）。当 h = 20 米时，t = ？秒（取正值）。",
                      "value": F(4), "cfg": "integer",
                      "l2": "5t² = 100 - 20 = 80，t² = 16。",
                      "solution": "5t² = 80 得 t² = 16，取正值 t = {value} 秒。"},
                     {"prompt": "小球离地高度 h = 60 - 5t²（米）。当 h = 40 米时，t = ？秒（取正值）。",
                      "value": F(2), "cfg": "integer",
                      "l2": "5t² = 60 - 40 = 20，t² = 4。",
                      "solution": "5t² = 20 得 t² = 4，取正值 t = {value} 秒。"},
                     {"prompt": "小球离地高度 h = 200 - 5t²（米）。当 h = 20 米时，t = ？秒（取正值）。",
                      "value": F(6), "cfg": "integer",
                      "l2": "5t² = 200 - 20 = 180，t² = 36。",
                      "solution": "5t² = 180 得 t² = 36，取正值 t = {value} 秒。"},
                 ])

    # F19 transfer：由面积求边长（mcq）
    qs += family(g, "transfer", 2,
                 "边长×边长 = 面积。",
                 "类比：面积 49 时边长 7。",
                 "想几乘几等于给定的面积，即为边长。",
                 [
                     {"prompt": "一个正方形的面积是 64 平方米，它的边长是（　）。", "correct": "8 米",
                      "wrongs": ["16 米", "4 米", "32 米"],
                      "l2": "边长是面积的算术平方根。",
                      "solution": "8×8 = 64，边长为 8 米，选 {key}。"},
                     {"prompt": "一个正方形的面积是 144 平方米，它的边长是（　）。", "correct": "12 米",
                      "wrongs": ["24 米", "6 米", "72 米"],
                      "l2": "边长是面积的算术平方根。",
                      "solution": "12×12 = 144，边长为 12 米，选 {key}。"},
                     {"prompt": "一个正方形的面积是 225 平方米，它的边长是（　）。", "correct": "15 米",
                      "wrongs": ["30 米", "75 米", "45 米"],
                      "l2": "边长是面积的算术平方根。",
                      "solution": "15×15 = 225，边长为 15 米，选 {key}。"},
                 ])

    # F20 screening：由周长求面积
    qs += family(g, "screening", 2,
                 "先由周长求边长：边长 = 周长 ÷ 4。",
                 "类比：周长 20 时边长 5，面积 25。",
                 "先算边长，再自乘，即为面积。",
                 [
                     {"prompt": "正方形的周长是 24 米，面积是多少平方米？", "value": F(36), "cfg": "integer",
                      "l2": "边长 = 24÷4 = 6。",
                      "solution": "边长 = 6 米，面积 = 6² = {value}（平方米）。"},
                     {"prompt": "正方形的周长是 36 米，面积是多少平方米？", "value": F(81), "cfg": "integer",
                      "l2": "边长 = 36÷4 = 9。",
                      "solution": "边长 = 9 米，面积 = 9² = {value}（平方米）。"},
                     {"prompt": "正方形的周长是 44 米，面积是多少平方米？", "value": F(121), "cfg": "integer",
                      "l2": "边长 = 44÷4 = 11。",
                      "solution": "边长 = 11 米，面积 = 11² = {value}（平方米）。"},
                 ])

    # F21 review：下落过程的性质（mcq）
    qs += family(g, "review", 2,
                 "t 从 0 增大时，t² 怎么变？",
                 "类比：20 - 5t² 在 t = 1 时是 15，t = 2 时是 0。",
                 "结合实际：高度不会超过初始高度，时间不为负。",
                 [
                     {"prompt": "小球离地高度 h = 45 - 5t²（米）。下列说法正确的是（　）。", "correct": "t 越大，h 越小",
                      "wrongs": ["h 可能大于 45 米", "t 可以取负数", "h 与 t 无关"],
                      "l2": "t 增大时 5t² 增大，h = 45 - 5t² 减小。",
                      "solution": "t 增大 → 5t² 增大 → h 减小；h 最高为 45，t 不取负值。选 {key}。"},
                     {"prompt": "小球离地高度 h = 100 - 5t²（米）。下列说法正确的是（　）。", "correct": "t 越大，h 越小",
                      "wrongs": ["h 可能大于 100 米", "t 可以取负数", "h 与 t 无关"],
                      "l2": "t 增大时 5t² 增大，h = 100 - 5t² 减小。",
                      "solution": "t 增大 → 5t² 增大 → h 减小；h 最高为 100，t 不取负值。选 {key}。"},
                     {"prompt": "小球离地高度 h = 60 - 5t²（米）。下列说法正确的是（　）。", "correct": "t 越大，h 越小",
                      "wrongs": ["h 可能大于 60 米", "t 可以取负数", "h 与 t 无关"],
                      "l2": "t 增大时 5t² 增大，h = 60 - 5t² 减小。",
                      "solution": "t 增大 → 5t² 增大 → h 减小；h 最高为 60，t 不取负值。选 {key}。"},
                 ])

    # F22 practice：边长倍数与面积倍数
    qs += family(g, "practice", 2,
                 "设小正方形边长为 1 份，大正方形边长是几份？",
                 "类比：边长 5 倍的正方形面积是 25 倍。",
                 "用倍数×倍数 算面积倍数。",
                 [
                     {"prompt": "大正方形的边长是小正方形的 2 倍，大正方形的面积是小正方形的几倍？",
                      "value": F(4), "cfg": "integer",
                      "l2": "面积 = 边长²，边长 2 倍则面积 2×2 倍。",
                      "solution": "面积倍数 = 2² = {value} 倍。"},
                     {"prompt": "大正方形的边长是小正方形的 3 倍，大正方形的面积是小正方形的几倍？",
                      "value": F(9), "cfg": "integer",
                      "l2": "面积 = 边长²，边长 3 倍则面积 3×3 倍。",
                      "solution": "面积倍数 = 3² = {value} 倍。"},
                     {"prompt": "大正方形的边长是小正方形的 4 倍，大正方形的面积是小正方形的几倍？",
                      "value": F(16), "cfg": "integer",
                      "l2": "面积 = 边长²，边长 4 倍则面积 4×4 倍。",
                      "solution": "面积倍数 = 4² = {value} 倍。"},
                 ])

    return qs


# ---------------------------------------------------------------- 主流程


def check_leaks(questions: list[dict]) -> list[str]:
    problems: list[str] = []
    for q in questions:
        hints = q["private_hints"]
        value = str(q["private_answer"]["value"])
        if q["type"] == "mcq":
            key = q["private_answer"]["value"]
            correct_text = next(o["text"] for o in q["public_options"] if o["key"] == key)
            for i, h in enumerate(hints):
                if f"选 {key}" in h:
                    problems.append(f"{q['id']} 提示含「选 {key}」")
                if i == 3 and correct_text in h:
                    problems.append(f"{q['id']} L4 提示泄露正确选项文本")
        else:
            for i, h in enumerate(hints):
                if ("." in value or "/" in value) and value in h:
                    problems.append(f"{q['id']} 提示泄露小数/分数答案 {value}")
                if i == 3 and value in h:
                    problems.append(f"{q['id']} L4 提示泄露答案 {value}")
        if q["private_solution"] in hints:
            problems.append(f"{q['id']} 解析与提示重复")
    return problems


def main() -> None:
    import json

    existing = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    old_ids = {q["id"] for q in existing}

    new_qs: list[dict] = []
    for cid, builder in [("C01", build_c01), ("C02", build_c02), ("C03", build_c03),
                         ("C04", build_c04), ("C05", build_c05), ("C06", build_c06)]:
        new_qs += [q for q in builder(Gen(cid)) if q["id"] not in old_ids]

    # 泄露自检
    problems = check_leaks(new_qs)
    if problems:
        print("泄露自检失败：")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)

    # 评分器答案自检
    for q in new_qs:
        result = scoring.grade_question(q, str(q["private_answer"]["value"]))
        if not result.correct:
            print(f"答案自检失败：{q['id']}")
            raise SystemExit(1)

    merged = existing + new_qs
    merged_ids = {q["id"] for q in merged}
    assert len(merged_ids) == len(merged), "题目 id 重复"

    # 写回前先做完整课程包校验
    QUESTIONS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    data = load_course()
    errors = validate_course(data)
    if errors:
        print("课程包校验失败（已写回，请修复后重试）：")
        for e in errors:
            print("  -", e)
        raise SystemExit(1)

    from collections import Counter

    print(f"生成完成：新增 {len(new_qs)} 题，全库 {len(merged)} 题。")
    print("按用途：", dict(Counter(q["purpose"] for q in merged)))
    print("按题型：", dict(Counter(q["type"] for q in merged)))
    print("按难度：", dict(sorted(Counter(q["difficulty"] for q in merged).items())))
    per_concept = Counter(q["primary_concept_id"] for q in merged)
    print("按概念：", dict(sorted(per_concept.items())))


if __name__ == "__main__":
    main()
