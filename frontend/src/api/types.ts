/** 后端响应信封与 DTO 类型（对齐 docs/API合同_v1.2.md） */

export interface Envelope<T> {
  data: T;
  next_action: { type: string; target_id?: string } | null;
  resource_version: number | null;
  trace_id: string | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string };
  trace_id: string | null;
}

export interface StudentDto {
  id: string;
  display_name: string;
  timezone: string;
  daily_minutes: number;
  created_at: string;
}

export interface MasteryEntry {
  concept_id: string;
  title: string;
  estimate: number | null;
  evidence_count: number;
  evidence_strength: number;
  status: string;
  review_due_at: string | null;
}

export interface GoalDto {
  id: string;
  course_id: string;
  target_concept_ids: string[];
  status: string;
  version: number;
}

export interface SessionDto {
  id: string;
  goal_id: string;
  status: string;
  current_task_id: string | null;
  version: number;
  updated_at: string;
}

export interface RecentEvidence {
  id: string;
  concept_id: string;
  attempt_id: string;
  family_id: string;
  score: number;
  eligible: boolean;
  exclusion_reason: string | null;
  created_at: string;
}

export interface OverviewData {
  student: StudentDto;
  goals: {
    goal: GoalDto;
    coverage: { assessed_count: number; total_count: number; ratio: number };
    mastery: MasteryEntry[];
    latest_session: { id: string; status: string; version: number } | null;
  }[];
  recent_evidence: RecentEvidence[];
  today_tasks: unknown[];
}

export interface PublicQuestion {
  id: string;
  course_id: string;
  primary_concept_id: string;
  family_id: string;
  type: 'mcq' | 'numeric';
  purpose: string;
  prompt: string;
  public_options: { key: string; text: string }[];
  difficulty: number;
  version: number;
}

export interface PathNode {
  concept_id: string;
  title: string;
  status: string;
  reason: string;
  eligible: boolean;
  review_due_at: string | null;
  tasks: { id: string; type: string; status: string; estimated_minutes: number }[];
}

export interface PlanDto {
  id: string;
  version: number;
  ordered_concept_ids: string[];
  reason_code: string;
  policy_version: string;
  active_task_ids: string[];
}

export interface PathData {
  plan: PlanDto | null;
  nodes: PathNode[];
  previous_plan: { id: string; version: number; ordered_concept_ids: string[]; reason_code: string } | null;
  stale: boolean;
  stale_note: string | null;
}

export interface TaskDto {
  id: string;
  concept_id: string;
  type: 'lesson' | 'practice' | 'review';
  status: string;
  estimated_minutes: number;
  version: number;
  plan_version?: number;
}

export interface TasksData {
  date: string;
  budget_minutes: number;
  pending_minutes: number;
  within_budget: boolean;
  tasks: TaskDto[];
  plan_version: number;
}

export interface AttemptResult {
  attempt: {
    id: string;
    exercise_id: string;
    question_id: string;
    answer: string;
    grade: string;
    hint_level_at_submission: number;
  };
  mastery_delta: {
    concept_id: string;
    before: { estimate: number | null; status: string };
    after: { estimate: number | null; status: string };
  };
  evidence: { id: string; eligible: boolean; exclusion_reason: string | null };
  versions: { exercise: number; assessment: number | null; session: number | null };
  transfer_available: boolean | null;
}

export interface DecisionDto {
  id: string;
  action: string;
  target_id: string | null;
  reason_code: string;
  evidence_ids: string[];
  input_state_version: number;
  planner_source: string;
  model_id: string | null;
  fallback_reason: string | null;
  created_at?: string;
}

export interface SnapshotEntry {
  concept_id: string;
  estimate: number | null;
  status: string;
  evidence_count: number;
}

export interface HistoryPoint {
  attempt_id: string | null;
  evidence_id: string | null;
  before: { estimate: number | null; status: string; evidence_count: number };
  after: { estimate: number | null; status: string; evidence_count: number };
  created_at: string;
}

/** T12-B Tutor Agent 启发式辅导 */
export interface ThinkingResult {
  exercise_id: string;
  feedback: string;
  possible_problem: string;
  socratic_question: string;
  planner_source: 'llm' | 'rule_fallback';
  model_id: string | null;
  fallback_reason: string | null;
  hint_level: number;
  duration_ms: number;
}

export interface TutoringTrace {
  exercise_id: string;
  status: string;
  hint_level: number;
  solution_seen: boolean;
  timeline: {
    type: 'start' | 'attempt' | 'hint' | 'solution' | 'thinking' | 'feedback';
    time: string;
    label: string;
    answer?: string;
    grade?: string;
    excerpt?: string;
    possible_problem?: string;
    level?: number;
    planner_source?: string;
  }[];
  current: { label: string };
  latest_feedback?: {
    feedback: string;
    possible_problem: string;
    socratic_question: string;
    planner_source: string;
    model_id: string | null;
  };
}

/** T10-B AI 学情诊断（结构化结果；与确定性评分分开保存） */
export interface DiagnosisReportData {
  report_id: string;
  status: 'ok' | 'insufficient_evidence';
  planner_source: 'llm' | 'rule_fallback';
  model_id: string | null;
  fallback_reason: string | null;
  summary: string;
  observations: { concept_id: string | null; title: string; detail: string }[];
  hypotheses: { concept_id: string | null; title: string; detail: string }[];
  recommended_probe: { concept_id: string | null; summary: string; reason: string };
  evidence_ids: string[];
  state?: {
    evidence_total: number;
    eligible_total: number;
    coverage: { assessed_count: number; total_count: number };
    mastery: { concept_id: string; title: string; status: string; estimate: number | null; evidence_count: number }[];
  };
  policy_version?: string;
  duration_ms?: number;
  created_at?: string;
}

/** T11-B 路径决策（含 T11-F 所需的调整前后/原因/当前任务/摘要字段） */
export interface PathDecisionData {
  decision_id: string;
  status: 'adjusted' | 'unchanged' | 'no_legal_action';
  candidate_actions: { action: string; target_id: string | null; reason_code: string; label?: string; message?: string }[];
  selected_action: { action: string; target_id: string | null; reason_code: string; reason?: string; label?: string };
  reason: string;
  evidence_ids: string[];
  policy_version: string;
  model_id: string | null;
  planner_source: string;
  fallback_reason: string | null;
  duration_ms: number;
  plan_before: { version: number; ordered_concept_ids: string[] } | null;
  plan_after: { version: number; ordered_concept_ids: string[] } | null;
  changed: boolean;
  current_task: { id: string; concept_id: string; type: string; status: string; estimated_minutes: number; version: number } | null;
  input_state_hash?: string;
  current_plan_version?: number;
  created_at?: string;
}
