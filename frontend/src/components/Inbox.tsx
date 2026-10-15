// "Waiting on you": the requests the agents prepared. Approving a payment or a
// purchase order is the only thing on the desk that moves cash, so it asks once
// more ("Pay $840.00 from checking?") and shows what checking will hold after.

import { useRef, useState } from 'react'
import { ApiError } from '../api'
import { isAgent } from '../agents'
import { approvalLook, blockingInvoices, money } from '../format'
import type { Approval, Cash } from '../types'
import { AgentDisc, ConfirmDialog } from './bits'
import { AlertIcon, CheckIcon, HandIcon, KeyIcon } from './Icons'

interface CardProps {
  a: Approval
  all: Approval[]
  cash: Cash | null
  approver: string
  askForName: () => void
  onDone: () => void
  onApprove: (a: Approval) => Promise<void>
  onReject: (a: Approval, note: string) => Promise<void>
}

function Card({ a, all, cash, approver, askForName, onDone, onApprove, onReject }: CardProps) {
  const look = approvalLook(a)
  const blockers = blockingInvoices(a, all)
  // A blocked order can only be paid after the invoices that block it, so count those too.
  const blockingCost = all
    .filter((x) => x.kind === 'invoice_payment' && x.status === 'pending' && blockers.includes(x.ref_id ?? -1))
    .reduce((s, x) => s + x.amount, 0)
  const after = cash ? cash.balance - a.amount - blockingCost : null
  const tooMuch = look.movesCash && after !== null && after < 0
  const [confirming, setConfirming] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)
  const hasName = !!approver.trim()

  const act = async (fn: () => Promise<void>) => {
    if (inFlight.current) return // a double click never sends a second decision
    inFlight.current = true
    setBusy(true)
    setError(null)
    try {
      await fn()
      setConfirming(false)
      setTimeout(onDone, 60) // after the dialog has closed, or focus would land behind the modal
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
      setConfirming(false)
    } finally {
      inFlight.current = false
      setBusy(false)
    }
  }
  const needName = (go: () => void) => () => (hasName ? go() : askForName())

  return (
    <li className={`req raised-sm req--${a.kind}`}>
      <div className="req__top">
        <span className="req__kind">{look.kindLabel}</span>
        <span className="req__amount">{look.movesCash ? money(a.amount) : 'No cash'}</span>
      </div>
      <h3 className="req__title">{look.title}</h3>
      <p className="req__detail small">{look.detail}</p>
      <p className="req__by small">
        {isAgent(a.requested_by) && <AgentDisc agent={a.requested_by} size={20} />} {a.requested_by} asks · ticket #{a.ticket_id} · request {a.approval_id}
      </p>
      <details className="req__why small">
        <summary>Why</summary>
        <p>{a.reason}</p>
      </details>
      {look.movesCash && after !== null && (
        <p className={`req__after small ${tooMuch ? 'neg' : ''}`}>
          Checking after{blockingCost > 0 ? ` invoice ${blockers.join(', ')} and this` : ''}: <strong>{money(after)}</strong>
          {tooMuch && ' (not enough cash; the pay step will refuse)'}
        </p>
      )}
      {blockers.length > 0 && (
        <p className="note note--warn small">
          <KeyIcon size={14} /> Pay invoice {blockers.join(', ')} first. The vendor won't ship while it's unpaid, so this order can't be
          approved yet.
        </p>
      )}
      {error && (
        <p className="note note--alert small" role="alert">
          <AlertIcon size={14} /> {error}
        </p>
      )}
      {rejecting ? (
        <div className="req__reject">
          <label className="small" htmlFor={`note-${a.approval_id}`}>Why reject? (optional, saved on the record)</label>
          <input id={`note-${a.approval_id}`} className="field" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} autoFocus />
          <div className="req__actions">
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRejecting(false)} disabled={busy}>Cancel</button>
            <button type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={() => act(() => onReject(a, note))}>
              {busy ? 'Rejecting…' : 'Reject request'}
            </button>
          </div>
        </div>
      ) : (
        <div className="req__actions">
          <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={needName(() => setRejecting(true))}>
            Reject
          </button>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={busy || blockers.length > 0}
            onClick={needName(() => (look.movesCash ? setConfirming(true) : act(() => onApprove(a))))}
          >
            <CheckIcon size={15} /> {blockers.length > 0 ? `Waiting on invoice ${blockers.join(', ')}` : look.movesCash ? `Approve ${money(a.amount)}` : 'Approve price'}
          </button>
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={`Pay ${money(a.amount)} from checking?`}
          body={
            <>
              <p>{look.title}</p>
              <p className="muted">
                Checking goes from {money(cash?.balance ?? 0)} to {money((cash?.balance ?? 0) - a.amount)}. This is recorded under your name,{' '}
                {approver.trim()}, and can't be undone from the desk.
              </p>
            </>
          }
          confirmLabel={`Pay ${money(a.amount)}`}
          busy={busy}
          onConfirm={() => act(() => onApprove(a))}
          onCancel={() => setConfirming(false)}
        />
      )}
    </li>
  )
}

export default function Inbox({
  approvals,
  ticketId,
  cash,
  approver,
  onApprover,
  onApprove,
  onReject,
}: {
  approvals: Approval[]
  ticketId: number
  cash: Cash | null
  approver: string
  onApprover: (name: string) => void
  onApprove: (a: Approval) => Promise<void>
  onReject: (a: Approval, note: string) => Promise<void>
}) {
  const heading = useRef<HTMLHeadingElement>(null)
  const nameField = useRef<HTMLInputElement>(null)
  const [nudge, setNudge] = useState(false)
  const pending = approvals.filter((a) => a.status === 'pending')
  const here = pending.filter((a) => a.ticket_id === ticketId)
  const elsewhere = pending.filter((a) => a.ticket_id !== ticketId)
  const decided = approvals.filter((a) => a.ticket_id === ticketId && a.status !== 'pending')
  const askForName = () => {
    setNudge(true)
    nameField.current?.focus()
  }
  const card = (a: Approval) => (
    <Card
      key={a.approval_id}
      a={a}
      all={approvals}
      cash={cash}
      approver={approver}
      askForName={askForName}
      onDone={() => heading.current?.focus()}
      onApprove={onApprove}
      onReject={onReject}
    />
  )

  return (
    <section className="panel inbox" aria-labelledby="inbox-title">
      <header className="panel__head">
        <h2 id="inbox-title" ref={heading} tabIndex={-1}>
          <HandIcon size={18} /> Waiting on you
        </h2>
        <span className="count-badge">{pending.length}</span>
      </header>
      <label className="approver">
        <span className="small">Approving as (your name goes on the record)</span>
        <input
          ref={nameField}
          className="field"
          value={approver}
          onChange={(e) => {
            onApprover(e.target.value)
            setNudge(false)
          }}
          placeholder="Your name"
          maxLength={100}
          autoComplete="name"
          required
          aria-invalid={nudge && !approver.trim()}
          aria-describedby="approver-hint"
        />
        <span id="approver-hint" className={`small ${nudge && !approver.trim() ? 'approver__nudge' : 'muted'}`}>
          {approver.trim() ? `Decisions are recorded as ${approver.trim()}.` : 'Type your name to approve or reject.'}
        </span>
      </label>
      {pending.length === 0 && <p className="muted small">Nothing to approve. The agents prepare payments and discounts here when a ticket needs them.</p>}
      {here.length > 0 && (
        <>
          <h3 className="inbox__group">For #{ticketId}</h3>
          <ul className="reqs">{here.map(card)}</ul>
        </>
      )}
      {elsewhere.length > 0 && (
        <details className="inbox__more" open={here.length === 0}>
          <summary>
            Other tickets <span className="muted">({elsewhere.length})</span>
          </summary>
          <ul className="reqs">{elsewhere.map(card)}</ul>
        </details>
      )}
      {decided.length > 0 && (
        <details className="inbox__more">
          <summary>
            Decided on #{ticketId} <span className="muted">({decided.length})</span>
          </summary>
          <ul className="decided small">
            {decided.map((a) => (
              <li key={a.approval_id}>
                <span className={`tag tag--${a.status}`}>{a.status}</span> {approvalLook(a).title}
                {a.decided_by && <span className="muted"> · {a.decided_by === 'system' ? 'the data changed, so it needs a new request' : a.decided_by}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
