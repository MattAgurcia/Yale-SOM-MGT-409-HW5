// The three tickets. Open work stands raised off the board; resolved work
// settles into it (pressed in) with a lime check.

import { ticketLine, typeLabel } from '../format'
import type { Approval, Ticket } from '../types'
import { StatusChip } from './bits'
import { CheckIcon } from './Icons'

export default function TicketRail({
  tickets,
  approvals,
  selected,
  runningId,
  onSelect,
}: {
  tickets: Ticket[]
  approvals: Approval[]
  selected: number | null
  runningId: number | null
  onSelect: (id: number) => void
}) {
  return (
    <section className="panel rail" aria-labelledby="rail-title">
      <header className="panel__head">
        <h2 id="rail-title">Tickets</h2>
        <span className="muted small">
          {tickets.filter((t) => t.status === 'resolved').length} of {tickets.length} resolved · <kbd>Alt</kbd>+<kbd>1</kbd>–<kbd>{tickets.length}</kbd>
        </span>
      </header>
      <ol className="tickets">
        {tickets.map((t) => {
          const pending = approvals.filter((a) => a.ticket_id === t.ticket_id && a.status === 'pending').length
          const resolved = t.status === 'resolved'
          const running = runningId === t.ticket_id
          return (
            <li key={t.ticket_id}>
              <button
                type="button"
                className={`ticket ${resolved ? 'ticket--resolved' : ''} ${running ? 'ticket--running' : ''} ${selected === t.ticket_id ? 'ticket--selected' : ''}`}
                aria-pressed={selected === t.ticket_id}
                onClick={() => onSelect(t.ticket_id)}
              >
                <span className="ticket__num" aria-hidden="true">{t.ticket_id}</span>
                <span className="ticket__body">
                  <span className="ticket__kicker">
                    {typeLabel[t.type] ?? t.type}
                  </span>
                  <span className="ticket__subject">
                    <span className="sr-only">Ticket {t.ticket_id}: </span>
                    {t.subject}
                  </span>
                  <span className="ticket__meta">{t.requester} · {ticketLine(t)}</span>
                  <span className="ticket__chips">
                    <StatusChip status={t.status} running={running} pending={pending} compact />
                    {pending > 0 && !running && (
                      <span className="count-badge" title={`${pending} request${pending > 1 ? 's' : ''} wait on you`}>
                        {pending} to approve
                      </span>
                    )}
                  </span>
                </span>
                {resolved && (
                  <span className="ticket__stamp" aria-hidden="true">
                    <CheckIcon size={20} />
                  </span>
                )}
              </button>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
