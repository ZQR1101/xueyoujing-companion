"""next_action.type 枚举与构造（API 合同 v1.1 修订项）。

取值为封闭集合；T06/T07 需要新取值时必须先修订合同再扩枚举。
start_task / retry_exercise / show_result 为 T05/T06 预留。
"""

from __future__ import annotations

import enum

from app.domain.errors import InternalError


class NextActionType(str, enum.Enum):
    next_question = "next_question"
    complete_assessment = "complete_assessment"
    start_task = "start_task"
    retry_exercise = "retry_exercise"
    show_result = "show_result"

    @property
    def owner_work_order(self) -> str:
        return _OWNER[self]


_OWNER = {
    NextActionType.next_question: "T04",
    NextActionType.complete_assessment: "T04",
    NextActionType.start_task: "T05",
    NextActionType.retry_exercise: "T06",
    NextActionType.show_result: "T06",
}


def build_next_action(action_type: NextActionType | str, target_id: str | None = None) -> dict:
    if isinstance(action_type, str):
        try:
            action_type = NextActionType(action_type)
        except ValueError:
            raise InternalError(f"未登记的 next_action.type：{action_type}") from None
    payload: dict = {"type": action_type.value}
    if target_id is not None:
        payload["target_id"] = target_id
    return payload
