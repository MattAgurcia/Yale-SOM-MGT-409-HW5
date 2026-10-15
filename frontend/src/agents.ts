// The five agents as the desk shows them, and how their live state, summaries
// and team-table edges are read from the audit-trail events.

import type { AgentName, DeskEvent } from './types'

export interface AgentMeta {
  name: AgentName
  short: string
  role: string
  /** CSS custom property holding the agent's palette colour (identity only, never meaning). */
  colorVar: string
  /** Where the centre of the agent's disc sits at the team table (percent of the table's box). A pentagon, so no three seats share a line. */
  seat: { x: number; y: number }
}

export const AGENTS: AgentMeta[] = [
  { name: 'Boss', short: 'Boss', role: 'Reads the ticket, decides who works it, makes the call', colorVar: '--agent-boss', seat: { x: 50, y: 15 } },
  { name: 'Inventory', short: 'Inventory', role: 'Stock by size, shortfalls, which vendor restocks', colorVar: '--agent-inventory', seat: { x: 14, y: 45 } },
  { name: 'Accounting', short: 'Accounting', role: 'Cash, invoices, margins; prepares payments for you', colorVar: '--agent-accounting', seat: { x: 32, y: 74 } },
  { name: 'Facilities', short: 'Facilities', role: 'The shop space: leases and rent', colorVar: '--agent-facilities', seat: { x: 68, y: 74 } },
  { name: 'Customer Service', short: 'Customers', role: 'Dan drafts customer replies (never sent)', colorVar: '--agent-cs', seat: { x: 86, y: 45 } },
]

export const AGENT_BY_NAME = Object.fromEntries(AGENTS.map((a) => [a.name, a])) as Record<AgentName, AgentMeta>

export const isAgent = (name: string | null | undefined): name is AgentName => !!name && name in AGENT_BY_NAME

export type AgentPhase = 'absent' | 'working' | 'waiting' | 'done' | 'stopped'

export interface AgentLive {
  phase: AgentPhase
  /** What the agent is doing right now, in a few words. */
  doing: string
  /** The last thing it said (a delegation or its report). */
  said: string | null
}

/** What a tool call looks like from across the room. */
const TOOL_VERB: Record<string, string> = {
  get_ticket: 'reading the ticket',
  list_tickets: 'scanning the board',
  check_stock_and_price: 'checking stock and price',
  check_invoice: 'checking the invoice',
  check_lease: 'checking the lease',
  list_vendors: 'comparing vendors',
  list_unpaid_invoices: 'going through unpaid bills',
  check_cash: 'checking cash',
  list_approvals: 'looking over approvals',
  list_drafts: 'reading drafts',
  request_payment: 'preparing a payment for you',
  create_purchase_order: 'drafting a purchase order',
  request_price_override: 'pricing the discount',
  save_customer_draft: 'writing a draft',
  update_ticket_status: 'updating the board',
}
/** The same, once it has happened ("checked the lease"). */
const TOOL_DONE: Record<string, string> = {
  get_ticket: 'read the ticket',
  list_tickets: 'scanned the board',
  check_stock_and_price: 'checked stock and price',
  check_invoice: 'checked the invoice',
  check_lease: 'checked the lease',
  list_vendors: 'compared vendors',
  list_unpaid_invoices: 'went through unpaid bills',
  check_cash: 'checked cash',
  list_approvals: 'looked over approvals',
  list_drafts: 'read drafts',
  request_payment: 'asked you to approve a payment',
  create_purchase_order: 'drafted a purchase order',
  request_price_override: 'asked you to approve a price',
  save_customer_draft: 'saved a draft',
  update_ticket_status: 'updated the board',
}
const verb = (tool: string) => TOOL_VERB[tool] ?? tool.replaceAll('_', ' ')
export const didVerb = (tool: string) => TOOL_DONE[tool] ?? tool.replaceAll('_', ' ')
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const toolWords = (tools: string[]) => sentence(tools.map(verb).join(', '))

/** Each agent's state at the end of the given events (one run, oldest first). */
export function agentStates(events: DeskEvent[]): Record<AgentName, AgentLive> {
  const state = Object.fromEntries(
    AGENTS.map((a) => [a.name, { phase: 'absent', doing: 'Not called on this run', said: null } as AgentLive]),
  ) as Record<AgentName, AgentLive>
  for (const e of events) {
    const who = e.agent
    if (!isAgent(who)) continue
    const s = state[who]
    switch (e.event) {
      case 'agent_start':
        s.phase = 'working'
        s.doing = 'Reading the request'
        break
      case 'model_step': {
        const calls = (e.detail.tool_calls as { tool: string }[] | undefined) ?? []
        const tools = calls.map((c) => c.tool).filter((t) => t !== 'ask_agent')
        if (calls.some((c) => c.tool === 'final_answer')) s.doing = 'Writing up the answer'
        else if (tools.length) s.doing = `${toolWords(tools)}…`
        else if (!calls.length) s.doing = 'Thinking'
        s.phase = 'working'
        if (e.said) s.said = e.said
        break
      }
      case 'tool_call':
        if (e.tools[0] !== 'ask_agent') {
          s.doing =
            e.detail.status === 'ok'
              ? (toolGist(e.tools[0], e.detail.result, e.detail.args) ?? `Done ${verb(e.tools[0])}`)
              : `${toolWords(e.tools)}: refused, adjusting`
        }
        break
      case 'delegation':
        s.phase = 'waiting'
        s.doing = `Waiting on ${String(e.detail.to)}`
        s.said = e.said
        break
      case 'delegation_refused':
      case 'delegation_failed':
        s.phase = 'working'
        s.doing = 'Carrying on without help'
        break
      case 'agent_end':
        s.phase = e.detail.stop_reason === 'final_answer' ? 'done' : 'stopped'
        s.doing = s.phase === 'done' ? 'Done' : `Stopped (${String(e.detail.stop_reason)})`
        if (e.said) s.said = e.said
        break
    }
  }
  return state
}

export interface AgentSummary {
  agent: AgentName
  involved: boolean
  runs: number
  askedBy: string[]
  asked: string[]
  tools: { tool: string; count: number; errors: number }[]
  writes: string[]
  finalWords: string | null
}

const WRITE_TOOLS = new Set(['request_payment', 'create_purchase_order', 'request_price_override', 'save_customer_draft', 'update_ticket_status'])

/** What each agent did over the given events: who asked it, whom it asked, tools, writes, last words. */
export function agentSummaries(events: DeskEvent[]): AgentSummary[] {
  const by = new Map<AgentName, AgentSummary>(
    AGENTS.map((a) => [a.name, { agent: a.name, involved: false, runs: 0, askedBy: [], asked: [], tools: [], writes: [], finalWords: null }]),
  )
  const runIds = new Map<AgentName, Set<string>>(AGENTS.map((a) => [a.name, new Set<string>()]))
  for (const e of events) {
    if (!isAgent(e.agent)) continue
    const s = by.get(e.agent)!
    if (e.event === 'agent_start') {
      s.involved = true
      if (e.run_id) runIds.get(e.agent)!.add(e.run_id)
    }
    if (e.event === 'delegation') {
      const to = String(e.detail.to)
      if (!s.asked.includes(to)) s.asked.push(to)
      if (isAgent(to) && !by.get(to)!.askedBy.includes(e.agent)) by.get(to)!.askedBy.push(e.agent)
    }
    if (e.event === 'tool_call' && e.tools[0] && e.tools[0] !== 'ask_agent') {
      const name = e.tools[0]
      let t = s.tools.find((x) => x.tool === name)
      if (!t) s.tools.push((t = { tool: name, count: 0, errors: 0 }))
      t.count += 1
      if (e.detail.status !== 'ok') t.errors += 1
      else if (WRITE_TOOLS.has(name)) s.writes.push(toolGist(name, e.detail.result, e.detail.args) ?? name)
    }
    if (e.event === 'agent_end' && e.said) s.finalWords = e.said
  }
  for (const s of by.values()) s.runs = runIds.get(s.agent)!.size
  return [...by.values()]
}

/** Who asked whom on this run, for the lines across the team table. */
export function delegationEdges(events: DeskEvent[]): { from: AgentName; to: AgentName; active: boolean }[] {
  const edges: { from: AgentName; to: AgentName; active: boolean }[] = []
  const ended = new Set<string>()
  for (const e of events) {
    if (e.event === 'delegation' && isAgent(e.agent) && isAgent(String(e.detail.to))) {
      const to = String(e.detail.to) as AgentName
      const existing = edges.find((x) => x.from === e.agent && x.to === to)
      if (existing) existing.active = true
      else edges.push({ from: e.agent, to, active: true })
      ended.delete(to)
    }
    if (e.event === 'agent_end' && isAgent(e.agent)) {
      ended.add(e.agent)
      for (const edge of edges) if (edge.to === e.agent) edge.active = false
    }
  }
  return edges
}

// --- Plain-English gists of tool results --------------------------------------------

type Obj = Record<string, unknown>
const money = (v: unknown) =>
  typeof v === 'number' ? v.toLocaleString('en-US', { style: 'currency', currency: 'USD' }) : String(v)

/** One short line saying what a tool call found or did, or null if there is nothing useful to say. */
export function toolGist(tool: string, result: unknown, args?: unknown): string | null {
  const r = (result ?? {}) as Obj
  const a = (args ?? {}) as Obj
  switch (tool) {
    case 'get_ticket': {
      const t = r.ticket as Obj | undefined
      return t ? `Read ticket ${t.ticket_id} (${String(t.status).replaceAll('_', ' ')})` : null
    }
    case 'list_tickets':
      return `${(r.tickets as unknown[] | undefined)?.length ?? 0} tickets on the board`
    case 'check_stock_and_price': {
      const q = r.requested as Obj | null
      const p = r.pricing as Obj | null
      const stock = q
        ? `${r.sku} ${q.size}: ${q.qty_on_hand} on hand` + (q.shortfall ? `, short ${q.shortfall}` : q.qty_needed ? ', enough' : '')
        : `${r.sku}: ${r.total_qty} on hand across sizes`
      return p ? `${stock} · cost ${money(p.unit_cost)}, list ${money(p.list_price)}` : stock
    }
    case 'check_invoice':
      return `Invoice ${r.invoice_id}: ${money(r.amount)}` + (r.is_overdue ? `, ${r.days_overdue} days overdue` : '') +
        (r.vendor_blocked ? ' · vendor blocked' : '')
    case 'check_lease':
      return `Rent ${money(r.monthly_rent)} due ${r.next_due} (${r.days_until_due} days)`
    case 'list_vendors': {
      const vs = (r.vendors as Obj[] | undefined) ?? []
      const blocked = vs.filter((v) => v.vendor_blocked).length
      return `${vs.length} vendors` + (blocked ? `, ${blocked} blocked by unpaid invoices` : '')
    }
    case 'list_unpaid_invoices':
      return `${(r.invoices as unknown[] | undefined)?.length ?? 0} unpaid invoices, ${money(r.total)}`
    case 'check_cash':
      return `Checking ${money(r.total_balance)} · pending ${money(r.pending_total)}`
    case 'list_approvals':
      return `${Array.isArray(result) ? result.length : 0} approval requests`
    case 'list_drafts':
      return `${Array.isArray(result) ? result.length : 0} drafts`
    case 'request_payment': {
      const ap = r.approval as Obj | undefined
      return ap ? `Asked you to approve ${money(ap.amount)} (${String(ap.kind).replaceAll('_', ' ')}, request ${ap.approval_id})` : null
    }
    case 'create_purchase_order': {
      const po = r.purchase_order as Obj | undefined
      const ap = r.approval as Obj | undefined
      return po ? `Drafted PO ${po.po_id}: ${po.qty} × ${po.sku} ${po.size}, ${money(po.total)} (request ${ap?.approval_id})` : null
    }
    case 'request_price_override': {
      const ap = r.approval as Obj | undefined
      const d = (ap?.details ?? {}) as Obj
      return ap ? `Asked to quote ${money(d.unit_price)} each for ${d.qty} (${d.discount_pct_off_list}% off, request ${ap.approval_id})` : null
    }
    case 'save_customer_draft': {
      const d = r.draft as Obj | undefined
      return d ? `Saved draft ${d.draft_id} to ${d.recipient} (not sent)` : null
    }
    case 'update_ticket_status':
      return `Set ticket ${r.ticket_id ?? a.ticket_id} to ${String(r.new_status ?? a.status).replaceAll('_', ' ')}`
    default:
      return null
  }
}
