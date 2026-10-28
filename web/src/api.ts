export type GuestSession = { token: string; expiresAt: string; mode: 'demo' };
export type ChatResponse = { reply: string; model: string; requestId: string };
export type HistoryItem = { role: 'user' | 'assistant'; content: string; createdAt: string };
export type HistoryResponse = { messages: HistoryItem[] };
export type LifeDraftItem = { kind: 'task' | 'schedule'; title: string; dueAt?: string; startsAt?: string; endsAt?: string };
export type LifeSuggestion = { items: LifeDraftItem[]; questions: string[]; model: string };
export type LifePlan = { jobId: number; status: string; intent: string; items: LifeDraftItem[]; saved: { kind: string; id: number }[]; approval: { id: number; decision: string; scope: string; expiresAt: string } };
export type SavedTask = { id: number; title: string; dueAt: string | null; status: string };
export type SavedSchedule = { id: number; title: string; startsAt: string; endsAt: string; status: string };
export type LifeItems = { tasks: SavedTask[]; schedules: SavedSchedule[] };
export type MorningReport = { date: string; tasks: SavedTask[]; schedules: SavedSchedule[]; sleep: { status: string; source: string; minutes: number | null } };
export type LifeJob = { jobId: number; status: string; decision: string; preview: string; latestEvent: string | null; createdAt: string; updatedAt: string; approvalExpiresAt: string };
export type LifeJobEvent = { seq: number; type: string; summary: string; timestamp: string };
type ErrorBody = { code: string; message: string; requestId: string; retryable: boolean };

const apiBase = import.meta.env.VITE_API_BASE_URL ??
  (['localhost', '127.0.0.1'].includes(window.location.hostname) ? 'http://127.0.0.1:8000' : '');
const storageKey = 'jarvis.demo.token';

export class ApiError extends Error {
  constructor(public code: string, message: string, public retryable: boolean) {
    super(message);
  }
}

async function readResponse<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null) as T | ErrorBody | null;
  if (!response.ok) {
    const error = body as ErrorBody | null;
    throw new ApiError(error?.code ?? 'HTTP_ERROR', error?.message ?? '服务暂时不可用。', error?.retryable ?? false);
  }
  if (!body) throw new ApiError('BAD_RESPONSE', '服务返回内容无法读取。', true);
  return body as T;
}

export async function createGuestSession(): Promise<GuestSession> {
  const response = await fetch(`${apiBase}/api/v1/demo/session`, { method: 'POST' });
  const session = await readResponse<GuestSession>(response);
  sessionStorage.setItem(storageKey, session.token);
  return session;
}

let pendingSession: Promise<{ session: GuestSession; renewed: boolean }> | null = null;

export function initializeGuestSession(): Promise<{ session: GuestSession; renewed: boolean }> {
  if (pendingSession) return pendingSession;
  pendingSession = (async () => {
    const token = sessionStorage.getItem(storageKey);
    if (token) {
      const response = await fetch(`${apiBase}/api/v1/demo/session`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        const status = await readResponse<{ expiresAt: string; mode: 'demo' }>(response);
        return { session: { ...status, token }, renewed: false };
      }
      if (response.status !== 401) await readResponse(response);
      sessionStorage.removeItem(storageKey);
      return { session: await createGuestSession(), renewed: true };
    }
    return { session: await createGuestSession(), renewed: false };
  })().finally(() => { pendingSession = null; });
  return pendingSession;
}

export async function renewGuestSession(): Promise<GuestSession> {
  sessionStorage.removeItem(storageKey);
  return createGuestSession();
}

export async function fetchHistory(token: string): Promise<HistoryResponse> {
  const response = await fetch(`${apiBase}/api/v1/chat/history`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return readResponse<HistoryResponse>(response);
}

export async function sendChat(token: string, message: string): Promise<ChatResponse> {
  const response = await fetch(`${apiBase}/api/v1/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ message }),
  });
  return readResponse<ChatResponse>(response);
}

export async function suggestLife(token: string, intent: string): Promise<LifeSuggestion> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/suggest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ intent }),
  });
  return readResponse<LifeSuggestion>(response);
}

export async function createLifePlan(token: string, intent: string, idempotencyKey: string, items?: LifeDraftItem[]): Promise<LifePlan> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/plans`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ intent, idempotencyKey, ...(items ? { items } : {}) }),
  });
  return readResponse<LifePlan>(response);
}

export async function fetchLifePlan(token: string, jobId: number): Promise<LifePlan> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/plans/${jobId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return readResponse<LifePlan>(response);
}

export async function editLifePlan(token: string, jobId: number, items: LifeDraftItem[]): Promise<LifePlan> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/plans/${jobId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ items }),
  });
  return readResponse<LifePlan>(response);
}

export async function decideLifePlan(token: string, jobId: number, decision: 'allow_once' | 'deny'): Promise<LifePlan> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/plans/${jobId}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ decision }),
  });
  return readResponse<LifePlan>(response);
}

export async function fetchLifeItems(token: string): Promise<LifeItems> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/items`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return readResponse<LifeItems>(response);
}

export async function updateLifeItem(token: string, kind: 'task' | 'schedule', id: number, body: Record<string, unknown>): Promise<void> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/items/${kind}/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  await readResponse(response);
}

export async function fetchMorning(token: string, date: string): Promise<MorningReport> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/morning?date=${encodeURIComponent(date)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return readResponse<MorningReport>(response);
}

export async function fetchLifeJobs(token: string): Promise<LifeJob[]> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/jobs`, { headers: { Authorization: `Bearer ${token}` } });
  return readResponse<LifeJob[]>(response);
}

export async function fetchLifeJobEvents(token: string, jobId: number): Promise<LifeJobEvent[]> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/jobs/${jobId}/events`, { headers: { Authorization: `Bearer ${token}` } });
  return readResponse<LifeJobEvent[]>(response);
}

export async function cancelLifeJob(token: string, jobId: number): Promise<void> {
  const response = await fetch(`${apiBase}/api/v1/demo/life/jobs/${jobId}/cancel`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
  await readResponse(response);
}
