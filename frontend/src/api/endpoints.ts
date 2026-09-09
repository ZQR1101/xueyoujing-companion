/** 端点封装：一个函数对应合同 v1.2 的一个端点 */

import { api, apiEnvelope } from './client';
import type {
  AttemptResult, DecisionDto, DiagnosisReportData, GoalDto, HistoryPoint, MasteryEntry,
  OverviewData, PathData, PathDecisionData, PublicQuestion, SessionDto, SnapshotEntry, TaskDto, TasksData,
  ThinkingResult, TutoringTrace,
} from './types';

export const getOverview = () => api<OverviewData>('GET', '/me/overview');
export const getMasteryHistory = (conceptId: string) =>
  api<{ concept_id: string; title: string; formula_version: string | null; points: HistoryPoint[] }>(
    'GET', `/me/mastery-history?concept_id=${encodeURIComponent(conceptId)}`,
  );

export const createGoal = (courseId: string, targetConceptIds: string[], dailyMinutes: number) =>
  api<{ goal: GoalDto; session: SessionDto }>('POST', '/goals', {
    course_id: courseId, target_concept_ids: targetConceptIds, daily_minutes: dailyMinutes,
  });

export const getSession = (sessionId: string) =>
  api<{
    session: SessionDto;
    goal: { id: string; course_id: string; status: string };
    resumable:
      | { kind: 'diagnosis'; assessment: { id: string; status: string; question_ids: string[]; version: number }; exercise: { id: string; status: string; version: number } | null; question: PublicQuestion | null }
      | { kind: 'learning'; exercise: { id: string; status: string; version: number; hint_level: number; solution_seen: boolean }; question: PublicQuestion }
      | null;
  }>('GET', `/sessions/${sessionId}`);

export const startDiagnosis = (sessionId: string, expectedVersion: number) =>
  api<{
    assessment: { id: string; status: string; question_ids: string[]; coverage: unknown; version: number };
    exercise: { id: string; status: string; version: number } | null;
    question: PublicQuestion | null;
    session: SessionDto;
  }>('POST', `/sessions/${sessionId}/diagnosis`, { expected_version: expectedVersion });

export const getAssessment = (assessmentId: string, afterExerciseId?: string) =>
  api<{
    assessment: { id: string; status: string; question_ids: string[]; coverage: { assessed: string[]; unassessed: string[] } | null; version: number };
    answered: { exercise_id: string; question_id: string; grade: string }[];
    next: { exercise: { id: string; status: string; version: number }; question: PublicQuestion } | null;
  }>('GET', `/assessments/${assessmentId}${afterExerciseId ? `?after_exercise_id=${encodeURIComponent(afterExerciseId)}` : ''}`);

export const completeAssessment = (assessmentId: string, expectedVersion: number) =>
  api<{
    snapshot: SnapshotEntry[];
    uncovered_concept_ids: string[];
    coverage: { assessed: string[]; unassessed: string[] };
    plan: { id: string; version: number; ordered_concept_ids: string[]; reason_code: string; policy_version: string; active_task_ids: string[] };
  }>('POST', `/assessments/${assessmentId}/complete`, { expected_version: expectedVersion });

export const submitAttempt = (exerciseId: string, answer: string, expectedVersion: number) =>
  apiEnvelope<AttemptResult>('POST', `/exercises/${exerciseId}/attempts`, {
    answer, expected_version: expectedVersion,
  });

export const requestHint = (exerciseId: string, expectedVersion: number) =>
  api<{ level: number; hint: string; exercise_version: number }>(
    'POST', `/exercises/${exerciseId}/hints`, { expected_version: expectedVersion },
  );

export const getExerciseAttempts = (exerciseId: string) =>
  api<{ attempts: { id: string; answer: string; grade: string; hint_level_at_submission: number; created_at: string }[] }>(
    'GET', `/exercises/${exerciseId}/attempts`,
  );

export const requestSolution = (exerciseId: string, expectedVersion: number) =>
  api<{
    solution_seen: boolean; answer: string; solution: string;
    concept_title: string; note: string; exercise_version: number;
  }>('POST', `/exercises/${exerciseId}/solution`, { expected_version: expectedVersion });

export const startNextTask = (sessionId: string, expectedVersion: number) =>
  api<
    | { resumed: boolean; task: TaskDto; content: { concept_id: string; source_id: string | null; title: string; excerpt: string; relevance_score: number | null }; note: string }
    | { resumed: boolean; task: TaskDto; exercise: { id: string; status: string; version: number; hint_level: number; solution_seen?: boolean }; question: PublicQuestion }
  >('POST', `/sessions/${sessionId}/start-next`, { expected_version: expectedVersion });

export const acknowledgeTask = (taskId: string, expectedVersion: number) =>
  api<{ task: TaskDto }>('POST', `/tasks/${taskId}/acknowledge`, { expected_version: expectedVersion });

export const pauseSession = (sessionId: string, expectedVersion: number) =>
  api<{ session: SessionDto; resume_hint: string }>('POST', `/sessions/${sessionId}/pause`, { expected_version: expectedVersion });

export const resumeSession = (sessionId: string, expectedVersion: number) =>
  api<{ session: SessionDto; resume_location: unknown }>('POST', `/sessions/{id}/resume`.replace('{id}', sessionId), { expected_version: expectedVersion });

export const getPath = (goalId: string) =>
  api<PathData>('GET', `/goals/${goalId}/path`);

export const replanGoal = (goalId: string, reason: string, expectedVersion: number) =>
  api<{ plan: { id: string; version: number; ordered_concept_ids: string[]; reason_code: string; policy_version: string; active_task_ids: string[] }; changed: boolean }>(
    'POST', `/goals/${goalId}/replan`, { reason, expected_version: expectedVersion },
  );

export const getTasks = (goalId: string, date?: string) =>
  api<TasksData>('GET', `/goals/${goalId}/tasks${date ? `?date=${encodeURIComponent(date)}` : ''}`);

export const sendMessage = (sessionId: string, text: string, expectedVersion: number) =>
  api<{
    reply: string;
    decision: DecisionDto & { session_completed?: boolean };
    legal_actions: { action: string; target_id: string | null; reason_code: string; message: string }[];
    session_status: string;
    session_completed: boolean;
  }>('POST', `/sessions/${sessionId}/messages`, { text, expected_version: expectedVersion });

export const getDecisions = (sessionId: string) =>
  api<{ decisions: DecisionDto[] }>('GET', `/sessions/${sessionId}/decisions`);

export const getReflections = (sessionId: string) =>
  api<{ reflections: { text: string; summary: unknown; created_at: string }[] }>(
    'GET', `/sessions/${sessionId}/reflections`,
  );

export const getSessionSummaryMetrics = (sessionId: string) =>
  api<{
    study_seconds: number;
    completed_task_count: number;
    independent_answer_count: number;
    new_eligible_evidence_count: number;
  }>('GET', `/sessions/${sessionId}/summary-metrics`);

export const saveReflection = (sessionId: string, text: string, expectedVersion: number) =>
  api<any>('POST', `/sessions/${sessionId}/reflection`, { text, expected_version: expectedVersion });

export const getPlans = (goalId: string) =>
  api<{
    plans: {
      id: string; version: number; reason_code: string; policy_version: string;
      ordered_concept_ids: string[]; evidence_ids: string[]; created_at: string;
    }[];
  }>('GET', `/goals/${goalId}/plans`);

/** T11-B 路径决策 */
export const getPathDecision = (goalId: string) =>
  api<PathDecisionData>('GET', `/goals/${goalId}/path-decision`);

export const createPathDecision = (goalId: string, expectedVersion: number) =>
  api<PathDecisionData>('POST', `/goals/${goalId}/path-decision`, { expected_version: expectedVersion });

export const listPathDecisions = (goalId: string) =>
  api<{ decisions: PathDecisionData[] }>('GET', `/goals/${goalId}/path-decisions`);

/** T10-B AI 学情诊断 */
export const getDiagnosisReport = (goalId: string) =>
  api<DiagnosisReportData>('GET', `/goals/${goalId}/diagnosis-report`);

export const createDiagnosisReport = (goalId: string) =>
  api<DiagnosisReportData>('POST', `/goals/${goalId}/diagnosis-report`, {});

/** T12-B Tutor Agent 启发式辅导 */
export const submitThinking = (exerciseId: string, text: string) =>
  apiEnvelope<ThinkingResult>('POST', `/exercises/${exerciseId}/thinking`, { text });

export const getTutoringTrace = (exerciseId: string) =>
  api<TutoringTrace>('GET', `/exercises/${exerciseId}/tutoring-trace`);

export type { MasteryEntry };

export const queryRag = (query: string, conceptId?: string) => api<any>('POST', '/tutoring/rag', { query, concept_id: conceptId, content_type: 'explanation' });
export const getMotivation = () => api<any>('GET', '/me/motivation');
export const getLeaderboard = () => api<any>('GET', '/motivation/leaderboard');
export const claimReward = (rewardId: string) => api<any>('POST', `/me/motivation/rewards/${encodeURIComponent(rewardId)}/claim`, {});
