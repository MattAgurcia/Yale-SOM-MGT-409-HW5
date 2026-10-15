// Formatting helpers: money, times, statuses, and plain-English approval titles.

import type { Approval, Ticket } from './types'

export const money = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit' })

export const prettyDate = (ymd: string) =>
  new Date(`${ymd}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })

export const typeLabel: Record<string, string> = {
  customer_order: 'Customer order',
  rent_notice: 'Rent notice',
  price_override: 'Bulk discount',
}

export interface StatusLook {
  label: string
  tone: 'idle' | 'live' | 'needs' | 'ready' | 'done' | 'alert'
  icon: 'dot' | 'spin' | 'hand' | 'check' | 'alert' | 'flag'
}

/** How a ticket's board status reads, given whether it is running and how many requests still wait on you. */
export function statusLook(status: string, running: boolean, pending?: number): StatusLook {
  if (running) return { label: 'Team working', tone: 'live', icon: 'spin' }
  switch (status) {
    case 'resolved':
      return { label: 'Resolved', tone: 'done', icon: 'check' }
    case 'waiting_approval':
      return pending === 0
        ? { label: 'Ready to close', tone: 'ready', icon: 'flag' }
        : { label: 'Needs your approval', tone: 'needs', icon: 'hand' }
    case 'in_progress':
      return { label: 'In progress', tone: 'live', icon: 'dot' }
    case 'escalated':
      return { label: 'Escalated', tone: 'alert', icon: 'alert' }
    default:
      return { label: 'Open', tone: 'idle', icon: 'dot' }
  }
}

export const ticketLine = (t: Ticket) => {
  if (t.type === 'rent_notice') return `Lease ${t.lease_id}`
  if (t.sku) return `${t.qty ?? ''} × ${t.sku}${t.size ? ` · size ${t.size}` : ''}`
  return t.subject
}

const str = (v: unknown) => (v === null || v === undefined ? '' : String(v))
const num = (v: unknown) => (typeof v === 'number' ? v : Number(v))

export interface ApprovalLook {
  kindLabel: string
  title: string
  detail: string
  movesCash: boolean
}

/** What an approval request is, in words a person would use. All values come from the request's details. */
export function approvalLook(a: Approval): ApprovalLook {
  const d = a.details
  switch (a.kind) {
    case 'invoice_payment':
      return {
        kindLabel: 'Pay an invoice',
        title: `Pay invoice ${str(d.invoice_id)} · ${str(d.vendor_name)}`,
        detail: `${str(d.description)} · due ${str(d.due_date)}` + (num(d.days_overdue) > 0 ? ` · ${str(d.days_overdue)} days overdue` : ''),
        movesCash: true,
      }
    case 'rent_payment':
      return {
        kindLabel: 'Pay rent',
        title: `Pay rent · ${str(d.space_name)}`,
        detail: `${str(d.landlord)} · due ${str(d.for_due_date)}` + (num(d.days_until_due) >= 0 ? ` (in ${str(d.days_until_due)} days)` : ''),
        movesCash: true,
      }
    case 'purchase_order':
      return {
        kindLabel: 'Purchase order',
        title: `Order ${str(d.qty)} × ${str(d.sku)} ${str(d.size)} · ${str(d.vendor_name)}`,
        detail: `${money(num(d.unit_cost))} each · arrives about ${str(d.lead_days)} days after you approve`,
        movesCash: true,
      }
    case 'price_override':
      return {
        kindLabel: 'Discount',
        title: `Quote ${money(num(d.unit_price))} each for ${str(d.qty)} × ${str(d.sku)}`,
        detail: `${str(d.discount_pct_off_list)}% off ${money(num(d.list_price))} · margin ${money(num(d.margin_per_unit))}/unit · quote ${money(num(d.quote_total))} · no cash moves`,
        movesCash: false,
      }
    default:
      return { kindLabel: a.kind, title: `Request ${a.approval_id}`, detail: a.reason, movesCash: a.amount > 0 }
  }
}

/**
 * A purchase order can only be approved once its vendor's invoices are paid.
 * Returns the invoice ids still waiting on you, from the request snapshot and
 * the invoice payments already approved.
 */
export function blockingInvoices(a: Approval, all: Approval[]): number[] {
  if (a.kind !== 'purchase_order') return []
  const blocked = (a.details.blocked_by_invoices as number[] | undefined) ?? []
  const paid = new Set(all.filter((x) => x.kind === 'invoice_payment' && x.status === 'approved').map((x) => x.ref_id))
  return blocked.filter((id) => !paid.has(id))
}
