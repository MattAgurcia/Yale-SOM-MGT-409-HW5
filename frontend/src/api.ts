// The desk talks to the FastAPI backend at http://localhost:8000 (set
// VITE_API_BASE in frontend/.env to change it). Each function is one route.

import type {
  Approval,
  Cash,
  DecisionResult,
  EventsResponse,
  Health,
  RunRecord,
  TicketDetail,
  TicketsResponse,
} from './types'

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://localhost:8000'

/** A route answered with an error; `status` is the HTTP code, `message` the backend's reason. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, `Can't reach the desk API at ${API_BASE}. Is the backend running?`)
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg?: string }) => d.msg).join('; ')
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as T
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  health: () => call<Health>('/api/health'),
  tickets: () => call<TicketsResponse>('/api/tickets'),
  ticket: (id: number) => call<TicketDetail>(`/api/tickets/${id}`),
  run: (id: number) => post<RunRecord>(`/api/tickets/${id}/run`),
  runInfo: (runId: string) => call<RunRecord>(`/api/runs/${runId}`),
  events: (since: number, limit = 500, ticketId?: number) =>
    call<EventsResponse>(`/api/events?since=${since}&limit=${limit}${ticketId ? `&ticket_id=${ticketId}` : ''}`),
  approvals: () => call<Approval[]>('/api/approvals'),
  approve: (id: number, approvedBy: string, note = '') =>
    post<DecisionResult>(`/api/approvals/${id}/approve`, { approved_by: approvedBy, note }),
  reject: (id: number, decidedBy: string, note = '') =>
    post<DecisionResult>(`/api/approvals/${id}/reject`, { decided_by: decidedBy, note }),
  cash: () => call<Cash>('/api/cash'),
  reset: () => post<{ database: string; sha256: string }>('/api/reset'),
}
