"""领域枚举：取值固定自规格书 §6/§10/§11，不得自行增删。"""

import enum


class GoalStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    paused = "paused"


class SessionStatus(str, enum.Enum):
    diagnosing = "diagnosing"
    ready = "ready"
    learning = "learning"
    paused = "paused"
    completed = "completed"


class AssessmentStatus(str, enum.Enum):
    in_progress = "in_progress"
    completed = "completed"
    abandoned = "abandoned"


class TaskType(str, enum.Enum):
    lesson = "lesson"
    practice = "practice"
    transfer = "transfer"
    review = "review"


class TaskStatus(str, enum.Enum):
    queued = "queued"
    active = "active"
    completed = "completed"
    deferred = "deferred"
    cancelled = "cancelled"


class ExerciseStatus(str, enum.Enum):
    open = "open"
    closed = "closed"


class AttemptGrade(str, enum.Enum):
    correct = "correct"
    incorrect = "incorrect"
    ungraded = "ungraded"


class MasteryStatus(str, enum.Enum):
    unassessed = "unassessed"
    developing = "developing"
    needs_support = "needs_support"
    mastered = "mastered"


class MemoryFactStatus(str, enum.Enum):
    active = "active"
    superseded = "superseded"
    retracted = "retracted"


class QuestionType(str, enum.Enum):
    mcq = "mcq"
    numeric = "numeric"


class QuestionPurpose(str, enum.Enum):
    screening = "screening"
    practice = "practice"
    transfer = "transfer"
    review = "review"


class EventType(str, enum.Enum):
    goal_created = "goal_created"
    diagnosis_started = "diagnosis_started"
    answer_submitted = "answer_submitted"
    answer_graded = "answer_graded"
    hint_shown = "hint_shown"
    solution_viewed = "solution_viewed"
    mastery_updated = "mastery_updated"
    plan_changed = "plan_changed"
    task_completed = "task_completed"
    session_paused = "session_paused"
    reflection_saved = "reflection_saved"
    # 合同 v1.2 R7：讲解任务三态拆分
    lesson_presented = "lesson_presented"
    lesson_acknowledged = "lesson_acknowledged"
    # T12-B：Tutor Agent 启发式辅导
    thinking_submitted = "thinking_submitted"
    tutor_feedback = "tutor_feedback"
