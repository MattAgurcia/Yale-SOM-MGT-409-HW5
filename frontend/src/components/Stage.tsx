// The selected ticket: what it asks for, the Run button, and how its latest run
// ended (the Boss's decision, the human actions it left you, and its cost).

import { useEffect, useState } from 'react'
import { prettyDate, ticketLine, typeLabel } from '../format'
import type { Approval, BossDecision, DeskEvent, RunRecord, Ticket } from '../types'
import { StatusChip } from './bits'
import { CheckIcon, HandIcon, PlayIcon, SpinIcon } from './Icons'

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  const s = Math.max(0, Math.round((now - new Date(since).getTime()) / 1000))
  return <span className="tabular">{Math.floor(s / 60)}:{String(s % 60).padStart(2, '0')}</span>
}

export default function Stage({
  ticket,
  approvals,
  runEnd,
  running,
  starting,
  online,
  resetSinceLastRun,
  justFinished,
  onRun,
}: {
  ticket: Ticket
  approvals: Approval[]
  runEnd: DeskEvent | null
  running: RunRecord | null
  starting: boolean
  online: boolean
  resetSinceLastRun: boolean
  justFinished: boolean
  onRun: () => void
}) {
  const mine = running?.ticket_id === ticket.ticket_id
  const busyElsewhere = running && !mine
  const pending = approvals.filter((a) => a.ticket_id === ticket.ticket_id && a.status === 'pending').length
  const resolved = ticket.status === 'resolved'
  const waiting = ticket.status === 'waiting_approval'

  let label = `Run the team on #${ticket.ticket_id}`
  let hint: React.ReactNode = 'The Boss reads the ticket and calls in only the teammates it needs.'
  let primary = true
  if (resolved) {
    label = 'Run again'
    hint = 'Already resolved. A new run re-checks the board from scratch.'
    primary = false
  } else if (waiting && pending > 0) {
    label = 'Run the team again'
    hint = (
      <>
        {pending} request{pending > 1 ? 's' : ''} for this ticket wait on you first, in <a href="#inbox-title">Waiting on you</a>.
      </>
    )
    primary = false
  } else if (waiting) {
    label = `Ask the Boss to close #${ticket.ticket_id}`
    hint = "You've decided every request. The Boss re-checks the board and can mark it resolved."
  }

  const decision = (runEnd?.detail.decision ?? null) as BossDecision | null
  const usage = runEnd?.detail.usage as { requests: number; total_tokens: number } | undefined

  return (
    <section className={`panel stage ${resolved ? 'stage--resolved' : ''}`} aria-labelledby="stage-title">
      <div className="stage__top">
        <div className="stage__num" aria-hidden="true">#{ticket.ticket_id}</div>
        <div className="stage__what">
          <p className="kicker">
            {typeLabel[ticket.type] ?? ticket.type} · from {ticket.requester} · opened {prettyDate(ticket.created_at.slice(0, 10))}
          </p>
          <h2 id="stage-title">{ticket.subject}</h2>
          <p className="stage__line">{ticketLine(ticket)}</p>
          {ticket.notes && <blockquote className="stage__notes">“{ticket.notes}”</blockquote>}
        </div>
        <div className="stage__status">
          <StatusChip status={ticket.status} running={mine} pending={pending} />
          {resolved && (
            <span className={`resolved-stamp ${justFinished ? 'resolved-stamp--new' : ''}`}>
              <CheckIcon size={18} /> Resolved
            </span>
          )}
        </div>
      </div>

      <div className="stage__run">
        <button
          type="button"
          className={`btn btn--run ${primary ? 'btn--primary' : 'btn--secondary'} ${mine ? 'is-pressed' : ''}`}
          onClick={onRun}
          disabled={!online || !!running || starting}
          aria-describedby="run-hint"
        >
          {mine || starting ? <SpinIcon size={18} /> : <PlayIcon size={16} />}
          {mine ? (
            <>
              Team working · <Elapsed since={running!.started_at} />
            </>
          ) : starting ? (
            'Starting…'
          ) : busyElsewhere ? (
            `Team is busy on #${running!.ticket_id}`
          ) : (
            label
          )}
        </button>
        <p id="run-hint" className="muted small">
          {mine ? (
            'Watch the team table: the agent speaking rises, the one waiting sinks. Nothing is paid or sent without you.'
          ) : busyElsewhere ? (
            'One ticket at a time, so two runs never race for the same cash.'
          ) : (
            <>
              {hint} Shortcut: <kbd>Alt</kbd>+<kbd>R</kbd>.
            </>
          )}
        </p>
      </div>

      {resetSinceLastRun && !mine && (
        <p className="note small">The shop data was reset after this ticket's last run, so that run no longer describes the board. Run the team again for a fresh story.</p>
      )}
      {decision && !mine && (
        <div className={`decision ${justFinished ? 'decision--new' : ''}`}>
          <div className="decision__head">
            <span className="decision__label">The Boss's call</span>
            <StatusChip status={decision.status} compact />
            {usage && (
              <span className="muted small">
                {usage.requests} model calls · {Math.round(usage.total_tokens / 1000)}k tokens · {String(runEnd?.detail.delegations_used ?? 0)} handoffs
              </span>
            )}
          </div>
          <p className="decision__text">{decision.decision}</p>
          {decision.human_actions.length > 0 && (
            <ul className="decision__actions">
              {decision.human_actions.map((h, i) => (
                <li key={i}>
                  <HandIcon size={15} /> {h}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {runEnd && !decision && !mine && (
        <p className="note note--alert">The last run stopped early ({String(runEnd.detail.stop_reason)}): {String(runEnd.detail.error ?? '')}</p>
      )}
    </section>
  )
}
