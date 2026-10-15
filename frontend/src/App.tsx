// The Campus Customs operations desk: pick a ticket, run the agent team, watch
// them work at the team table, approve what they prepare, and see the cash move.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, API_BASE, ApiError } from './api'
import { approvalLook, money, prettyDate } from './format'
import type { Approval, DeskEvent, TicketDetail } from './types'
import { useDesk } from './useDesk'
import { ConfirmDialog } from './components/bits'
import ActivityFeed from './components/ActivityFeed'
import CashVault from './components/CashVault'
import Drafts from './components/Drafts'
import Inbox from './components/Inbox'
import Stage from './components/Stage'
import TeamTable from './components/TeamTable'
import TicketRail from './components/TicketRail'
import WhoDidWhat from './components/WhoDidWhat'
import { AlertIcon, ResetIcon } from './components/Icons'

interface Toast {
  id: number
  text: string
  tone: 'ok' | 'info' | 'alert'
}

const errText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e))

export default function App() {
  const desk = useDesk()
  const tickets = useMemo(() => desk.board?.tickets ?? [], [desk.board])
  const [selected, setSelected] = useState<number | null>(null)
  const [detail, setDetail] = useState<TicketDetail | null>(null)
  const [scope, setScope] = useState<'run' | 'all'>('run')
  const [approver, setApprover] = useState(() => localStorage.getItem('cc-approver') ?? '')
  const [toasts, setToasts] = useState<Toast[]>([])
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetting, setResetting] = useState(false)
  const historyAsked = useRef(new Set<number>())

  const toast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5200)
  }, [])

  useEffect(() => localStorage.setItem('cc-approver', approver), [approver])

  // Start on the running ticket, else the first one.
  useEffect(() => {
    if (selected === null && tickets.length) setSelected(desk.board?.running_ticket_id ?? tickets[0].ticket_id)
  }, [selected, tickets, desk.board])

  // The selected ticket's drafts and history, re-read whenever the board is.
  useEffect(() => {
    if (selected === null) return
    let live = true
    api.ticket(selected).then((d) => live && setDetail(d)).catch(() => {})
    return () => {
      live = false
    }
  }, [selected, desk.boardVersion])

  // Tell the human when a run ends (including runs started from elsewhere).
  useEffect(() => {
    const f = desk.finished
    if (!f) return
    const status = f.decision?.status
    if (f.status === 'completed') {
      toast(`#${f.ticket_id}: the team finished${status ? ` (${status.replaceAll('_', ' ')})` : ''}.`, status === 'resolved' ? 'ok' : 'info')
    } else {
      toast(`#${f.ticket_id}: the run stopped (${f.status.replaceAll('_', ' ')}).`, 'alert')
    }
  }, [desk.finished, toast])

  const ticket = tickets.find((t) => t.ticket_id === selected) ?? null

  // Everything on this ticket, and the newest database reset (older runs no longer describe the data).
  const ticketEvents = useMemo(
    () => desk.events.filter((e) => e.ticket_id === selected || e.event === 'db_reset'),
    [desk.events, selected],
  )
  const lastResetSeq = useMemo(() => {
    for (let i = ticketEvents.length - 1; i >= 0; i--) if (ticketEvents[i].event === 'db_reset') return ticketEvents[i].seq
    return 0
  }, [ticketEvents])
  const sinceReset = useMemo(
    () => ticketEvents.filter((e) => e.seq > lastResetSeq && e.event !== 'db_reset'),
    [ticketEvents, lastResetSeq],
  )
  const latestStart = useMemo(() => [...sinceReset].reverse().find((e) => e.event === 'run_start') ?? null, [sinceReset])
  const live = !!desk.running && desk.running.ticket_id === selected
  // While a just-started run's first events are on their way, show a clean slate, not the previous run.
  const pendingStart = live && latestStart?.run_id !== desk.running?.run_id
  const runEvents: DeskEvent[] = useMemo(() => {
    if (!latestStart || pendingStart) return []
    return sinceReset.filter((e) => e.run_id === latestStart.run_id || (e.event === 'human_decision' && e.seq > latestStart.seq))
  }, [sinceReset, latestStart, pendingStart])
  const runEnd = runEvents.find((e) => e.event === 'run_end') ?? null
  const resetSinceLastRun = lastResetSeq > 0 && !latestStart && ticketEvents.some((e) => e.event === 'run_start')

  // If the first load did not reach this ticket's runs, fetch its history once.
  useEffect(() => {
    if (selected === null || historyAsked.current.has(selected) || !desk.board) return
    if (!ticketEvents.some((e) => e.event === 'run_start' && e.ticket_id === selected)) {
      historyAsked.current.add(selected)
      desk.loadTicketHistory(selected).catch(() => {})
    }
  }, [selected, ticketEvents, desk])

  const startRun = useCallback(async () => {
    if (!ticket || desk.running || desk.starting) return
    try {
      await desk.run(ticket.ticket_id)
      setScope('run')
      toast(`The team is on #${ticket.ticket_id}.`)
    } catch (e) {
      toast(errText(e), 'alert')
    }
  }, [ticket, desk, toast])

  const afterHumanDecision = useCallback(
    (a: Approval) => {
      const left = desk.approvals.filter((x) => x.ticket_id === a.ticket_id && x.status === 'pending' && x.approval_id !== a.approval_id)
      if (left.length === 0) toast(`Every request on #${a.ticket_id} is decided. Ask the Boss to close it.`, 'info')
    },
    [desk.approvals, toast],
  )

  const onApprove = useCallback(
    async (a: Approval) => {
      try {
        const r = await desk.approve(a.approval_id, approver.trim())
        toast(r.payment ? `Paid ${money(r.payment.amount)} · checking now ${money(r.cash_balance_after ?? 0)}` : `Approved: ${approvalLook(a).title}`, 'ok')
        afterHumanDecision(a)
      } catch (e) {
        toast(errText(e), 'alert')
        throw e
      }
    },
    [desk, approver, toast, afterHumanDecision],
  )
  const onReject = useCallback(
    async (a: Approval, note: string) => {
      try {
        await desk.reject(a.approval_id, approver.trim(), note)
        toast(`Rejected request ${a.approval_id}. Nothing was paid.`)
        afterHumanDecision(a)
      } catch (e) {
        toast(errText(e), 'alert')
        throw e
      }
    },
    [desk, approver, toast, afterHumanDecision],
  )

  // Keyboard: Alt+1..3 pick a ticket, Alt+R runs the team (a modifier, so stray keys never start a run).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.repeat || e.metaKey || e.ctrlKey || document.querySelector('dialog[open]')) return
      const digit = /^Digit([1-9])$/.exec(e.code)
      if (digit && Number(digit[1]) <= tickets.length) {
        e.preventDefault()
        setSelected(tickets[Number(digit[1]) - 1].ticket_id)
      }
      if (e.code === 'KeyR') {
        e.preventDefault()
        startRun()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [tickets, startRun])

  const troubled = !!desk.problem || desk.health?.ok === false

  return (
    <div className="app">
      <a className="skip" href="#inbox-title">Skip to requests waiting on you</a>
      <header className="masthead">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">CC</span>
          <div>
            <h1>Campus Customs</h1>
            <p className="brand__sub">Operations desk · the agent team at work</p>
          </div>
        </div>
        <div className="masthead__right">
          {desk.board && <span className="pill">Shop date {prettyDate(desk.board.date_today)}</span>}
          <span className={`pill ${!desk.online || troubled ? 'pill--alert' : 'pill--ok'}`}>
            <span className="pulse-dot" aria-hidden="true" />{' '}
            {!desk.online ? 'Desk offline' : troubled ? 'Desk needs attention' : `Desk connected · ${desk.health?.model ?? 'gpt-6-luna'}`}
          </span>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => setConfirmReset(true)} disabled={!!desk.running || !desk.online}>
            <ResetIcon size={15} /> Reset shop data
          </button>
        </div>
      </header>

      {!desk.online && (
        <div className="banner" role="alert">
          <AlertIcon size={18} />
          <div>
            <strong>Can't reach the desk API at {API_BASE}.</strong> Start the backend from the <code>backend/</code> folder with the
            project's virtual environment active: <code>uvicorn main:app --reload --port 8000</code>. The board reconnects on its own.
          </div>
        </div>
      )}
      {desk.online && desk.problem && (
        <div className="banner" role="alert">
          <AlertIcon size={18} />
          <div>
            <strong>Something needs attention.</strong> {desk.problem} The board keeps retrying.
          </div>
        </div>
      )}

      <main className="desk">
        <div className="col col--left">
          <TicketRail
            tickets={tickets}
            approvals={desk.approvals}
            selected={selected}
            runningId={desk.running?.ticket_id ?? null}
            onSelect={setSelected}
          />
          <CashVault cash={desk.cash} />
        </div>

        <div className="col col--center">
          {ticket ? (
            <>
              <Stage
                ticket={ticket}
                approvals={desk.approvals}
                runEnd={runEnd}
                running={desk.running}
                starting={desk.starting}
                online={desk.online}
                resetSinceLastRun={resetSinceLastRun}
                justFinished={desk.finished?.ticket_id === ticket.ticket_id}
                onRun={startRun}
              />
              <TeamTable events={runEvents} live={live} />
              <ActivityFeed events={scope === 'run' ? runEvents : ticketEvents} scope={scope} onScope={setScope} ticketId={ticket.ticket_id} live={live} />
            </>
          ) : (
            <section className="panel">
              <p className="muted">{desk.online ? 'Loading the board…' : 'Waiting for the desk API…'}</p>
            </section>
          )}
        </div>

        <div className="col col--right">
          {ticket && (
            <>
              <Inbox
                approvals={desk.approvals}
                ticketId={ticket.ticket_id}
                cash={desk.cash}
                approver={approver}
                onApprover={setApprover}
                onApprove={onApprove}
                onReject={onReject}
              />
              <WhoDidWhat events={sinceReset} />
              <Drafts drafts={detail?.ticket.ticket_id === ticket.ticket_id ? detail.drafts : []} />
            </>
          )}
        </div>
      </main>

      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>
            {t.text}
          </div>
        ))}
      </div>

      {confirmReset && (
        <ConfirmDialog
          title="Reset the shop data?"
          body={
            <p className="muted">
              The working database goes back to the original: every ticket open, checking back to its starting balance, and all
              approvals, drafts and orders gone. The audit trail keeps everything, including this reset.
            </p>
          }
          confirmLabel="Reset"
          tone="danger"
          busy={resetting}
          onCancel={() => setConfirmReset(false)}
          onConfirm={async () => {
            if (resetting) return
            setResetting(true)
            try {
              await desk.reset()
              toast('Shop data reset to the original.', 'ok')
            } catch (e) {
              toast(errText(e), 'alert')
            } finally {
              setResetting(false)
              setConfirmReset(false)
            }
          }}
        />
      )}
    </div>
  )
}
