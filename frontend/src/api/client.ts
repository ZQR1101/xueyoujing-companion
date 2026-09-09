/** API 客户端：演示令牌自动签发、幂等键、统一信封解包 */

import type { Envelope, StudentDto } from './types';

const TOKEN_KEY = 'xyj.demo.token';
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const API_ORIGIN = API_BASE.replace(/\/api\/v1$/, '');

export type RuntimeStatus = {
  status: 'ready' | 'degraded';
  curriculum: { course_id: string; concept_count: number; question_count: number };
  rag: { segment_count: number; index_version: string };
  llm: {
    provider: string;
    model_id: string | null;
    configured: boolean;
    timeout_seconds: number;
    rule_fallback_available: boolean;
  };
};

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function readStored(): { token: string; student: StudentDto } | null {
  try {
    const raw = localStorage.getItem(TOKEN_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function currentStudent(): StudentDto | null {
  return readStored()?.student ?? null;
}

export async function ensureIdentity(): Promise<StudentDto> {
  const stored = readStored();
  if (stored) return stored.student;
  const r = await fetch(`${API_BASE}/demo-identities`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ display_name: '李同学' }),
  });
  const body = await r.json();
  if (!r.ok) throw new ApiError(body?.error?.code ?? 'unknown', body?.error?.message ?? '请求失败', r.status);
  const payload = body as Envelope<{ token: string; student: StudentDto }>;
  localStorage.setItem(
    TOKEN_KEY,
    JSON.stringify({ token: payload.data.token, student: payload.data.student }),
  );
  return payload.data.student;
}

export function resetIdentity(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/** 无需登录的路演预检。失败时由界面明确显示离线，而不是伪装成可用。 */
export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  const response = await fetch(`${API_ORIGIN}/readyz`);
  if (!response.ok) throw new ApiError('readiness_failed', `运行预检失败（${response.status}）`, response.status);
  return response.json() as Promise<RuntimeStatus>;
}

let keyCounter = 0;

export async function api<T>(
  method: 'GET' | 'POST',
  path: string,
  payload?: unknown,
): Promise<T> {
  return (await apiEnvelope<T>(method, path, payload)).data;
}

/** 同时取回信封级 next_action（作答/任务类端点需要） */
export async function apiEnvelope<T>(
  method: 'GET' | 'POST',
  path: string,
  payload?: unknown,
): Promise<{ data: T; next_action: { type: string; target_id?: string } | null }> {
  const stored = readStored();
  if (!stored) await ensureIdentity();
  const auth = readStored();
  if (!auth) throw new ApiError('identity_failed', '演示身份签发失败', 500);

  const headers: Record<string, string> = {
    Authorization: `Bearer ${auth.token}`,
    'Content-Type': 'application/json',
  };
  if (method === 'POST') headers['Idempotency-Key'] = `${crypto.randomUUID()}-${keyCounter++}`;

  const r = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const err = body as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(
      err?.error?.code ?? 'unknown',
      err?.error?.message ?? `请求失败（${r.status}）`,
      r.status,
    );
  }
  const envelope = body as Envelope<T>;
  return { data: envelope.data, next_action: envelope.next_action };
}
