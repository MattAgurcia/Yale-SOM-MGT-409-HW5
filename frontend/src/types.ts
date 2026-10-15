// Shapes returned by the FastAPI backend (backend/main.py). Every shop value in
// them comes from the MCP server over the shop database.

export type AgentName = 'Boss' | 'Inventory' | 'Accounting' | 'Facilities' | 'Customer Service'
export type TicketStatus = 'open' | 'in_progress' | 'waiting_approval' | 'resolved' | 'escalated'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'stale'
export type RunStatus = 'running' | 'completed' | 'usage_limit' | 'error' | 'cancelled'

export interface Ticket {
  ticket_id: number
  type: string
  requester: string
  subject: string
  sku: string | null
  size: string | null
  qty: number | null
  lease_id: number | null
  invoice_id: number | null
  status: TicketStatus | string
  notes: string | null
  created_at: string
  state?: 'open' | 'resolved'
  running?: boolean
}

export interface TicketsResponse {
  date_today: string
  tickets: Ticket[]
  running_ticket_id: number | null
}

export interface TicketUpdate {
  update_id: number
  status: string
  note: string
  updated_by: string
  created_at: string
}

export interface Draft {
  draft_id: number
  ticket_id: number
  recipient: string
  subject: string
  body: string
  status: string
  written_by: string
  created_at: string
}

export interface Approval {
  approval_id: number
  ticket_id: number
  kind: 'invoice_payment' | 'rent_payment' | 'purchase_order' | 'price_override' | string
  ref_id: number | null
  amount: number
  details: Record<string, unknown>
  reason: string
  requested_by: string
  requested_at: string
  shop_date: string
  status: ApprovalStatus | string
  decided_by: string | null
  decided_at: string | null
  decision_note: string | null
  payment_id: number | null
}

export interface TicketDetail {
  date_today: string
  ticket: Ticket
  updates: TicketUpdate[]
  drafts: Draft[]
  approvals: Approval[]
}

export interface Payment {
  payment_id: number
  kind: string
  ref_id: number | null
  amount: number
  account: string
  paid_at: string
  approved_by: string
}

export interface Cash {
  account: string
  balance: number
  as_of: string
  date_today: string
  pending_total: number
  pending_payments: { approval_id: number; ticket_id: number; kind: string; amount: number }[]
  balance_if_all_pending_paid: number
  can_cover_all_pending: boolean
  payments: Payment[]
}

export interface BossDecision {
  ticket_id: number
  status: TicketStatus
  decision: string
  rationale: string
  agents_consulted: AgentName[]
  facts: { fact: string; source: string }[]
  approval_ids: number[]
  draft_ids: number[]
  human_actions: string[]
  next_steps: string[]
}

export interface TicketRun {
  run_id: string
  ticket_id: number
  stop_reason: RunStatus
  decision: BossDecision | null
  error: string | null
  delegations_used: number
  usage: { requests: number; tool_calls: number; input_tokens: number; output_tokens: number; total_tokens: number }
}

export interface RunRecord {
  run_id: string
  ticket_id: number
  status: RunStatus
  started_at: string
  finished_at: string | null
  result: TicketRun | null
  error: string | null
}

/** One step from the audit trail, as GET /api/events shapes it. */
export interface DeskEvent {
  seq: number
  ts: string
  event: string
  run_id: string | null
  ticket_id: number | null
  agent: string | null
  depth: number | null
  said: string | null
  tools: string[]
  detail: Record<string, unknown>
}

export interface EventsResponse {
  events: DeskEvent[]
  last_seq: number
  has_more: boolean
  older_events_not_shown: number
  trail_restarted: boolean
  running: RunRecord | null
}

export interface Health {
  ok: boolean
  desk: 'up' | 'down'
  database: string
  audit_file: string
  model: string
  running: RunRecord | null
}

export interface DecisionResult {
  approval: Approval
  payment: Payment | null
  cash_balance_after: number | null
  changes: string[]
  cash?: Cash
}
