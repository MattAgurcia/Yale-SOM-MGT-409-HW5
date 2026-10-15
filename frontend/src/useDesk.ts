// The desk's live state: tickets, cash, approvals and the agent event stream,
// kept fresh by polling the backend (fast while a run is going, slow when idle).

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import type { Approval, BossDecision, Cash, DecisionResult, DeskEvent, Health, RunRecord, RunStatus, TicketsResponse } from './types'

const FAST_MS = 1000 // while the team is working
const SLOW_MS = 4000 // idle
const OFFLINE_MS = 5000 // backend unreachable
const MAX_EVENTS = 5000 // keep memory bounded on a long-open desk

/** A run that ended, read from its run_end event in the audit trail. */
export interface FinishedRun {
  run_id: string
  ticket_id: number
  status: RunStatus
  decision: BossDecision | null
}

export interface Desk {
  online: boolean
  /** Something is wrong even though the API answers (MCP server down, database missing...). */
  problem: string | null
  health: Health | null
  board: TicketsResponse | null
  cash: Cash | null
  approvals: Approval[]
  events: DeskEvent[]
  running: RunRecord | null
  starting: boolean
  /** The most recent run that ended while the desk was open. */
  finished: FinishedRun | null
  boardVersion: number
  run: (ticketId: number) => Promise<RunRecord>
  approve: (approvalId: number, approvedBy: string, note?: string) => Promise<DecisionResult>
  reject: (approvalId: number, decidedBy: string, note?: string) => Promise<DecisionResult>
  reset: () => Promise<void>
  loadTicketHistory: (ticketId: number) => Promise<void>
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useDesk(): Desk {
  const [online, setOnline] = useState(true)
  const [problem, setProblem] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [board, setBoard] = useState<TicketsResponse | null>(null)
  const [cash, setCash] = useState<Cash | null>(null)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [events, setEvents] = useState<DeskEvent[]>([])
  const [running, setRunning] = useState<RunRecord | null>(null)
  const [starting, setStarting] = useState(false)
  const [finished, setFinished] = useState<FinishedRun | null>(null)
  const [boardVersion, setBoardVersion] = useState(0)

  const lastSeq = useRef(0)
  const runningRef = useRef<RunRecord | null>(null)
  const lastBoardAt = useRef(0)
  const lastHealthAt = useRef(0)
  const seenEnds = useRef<Set<string> | null>(null) // run_ids whose run_end we have already reported
  const pulling = useRef<Promise<void> | null>(null)
  const startingRef = useRef(false)

  const refreshBoard = useCallback(async () => {
    const [b, c, a] = await Promise.all([api.tickets(), api.cash(), api.approvals()])
    setBoard(b)
    setCash(c)
    setApprovals(a)
    setBoardVersion((v) => v + 1)
    lastBoardAt.current = Date.now()
  }, [])

  const mergeEvents = useCallback((fresh: DeskEvent[], replace = false) => {
    setEvents((prev) => {
      const base = replace ? [] : prev
      const seen = new Set(base.map((e) => e.seq))
      const merged = [...base, ...fresh.filter((e) => !seen.has(e.seq))].sort((a, b) => a.seq - b.seq)
      return merged.length > MAX_EVENTS ? merged.slice(-MAX_EVENTS) : merged
    })
  }, [])

  // One pull at a time, so an older response can never overwrite a newer one.
  const pullEvents = useCallback(() => {
    if (pulling.current) return pulling.current
    const job = (async () => {
      const fresh: DeskEvent[] = []
      let since = lastSeq.current
      let restarted = false
      let now: RunRecord | null = null
      for (let page = 0; page < 20; page++) {
        const r = await api.events(since, since === 0 ? 1000 : 500)
        if (r.trail_restarted) restarted = true
        fresh.push(...r.events)
        since = r.last_seq
        now = r.running
        if (!r.has_more) break
      }
      lastSeq.current = since
      if (restarted || fresh.length) mergeEvents(fresh, restarted)

      // Runs that ended since the last pull (including runs started elsewhere).
      const ends = fresh.filter((e) => e.event === 'run_end' && e.run_id)
      if (seenEnds.current === null) {
        seenEnds.current = new Set(ends.map((e) => e.run_id!)) // first load: history, not news
      } else {
        const news = ends.filter((e) => !seenEnds.current!.has(e.run_id!))
        news.forEach((e) => seenEnds.current!.add(e.run_id!))
        const last = news.at(-1)
        if (last) {
          setFinished({
            run_id: last.run_id!,
            ticket_id: last.ticket_id!,
            status: last.detail.stop_reason as RunStatus,
            decision: (last.detail.decision as BossDecision | undefined) ?? null,
          })
        }
        if (news.length) lastBoardAt.current = 0 // re-read the board on this tick
      }
      runningRef.current = now
      setRunning(now)
    })()
    pulling.current = job
    job.finally(() => {
      pulling.current = null
    })
    return job
  }, [mergeEvents])

  // The polling loop.
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      let delay = SLOW_MS
      let trouble: string | null = null
      try {
        if (Date.now() - lastHealthAt.current > 15000) {
          const h = await api.health()
          setHealth(h)
          lastHealthAt.current = Date.now()
          if (!h.ok) trouble = "The shop's MCP server is not responding, so the board may be out of date."
        }
        try {
          await pullEvents()
        } catch (e) {
          if (e instanceof ApiError && e.status === 0) throw e
          trouble = `Agent events could not be read: ${message(e)}`
        }
        const boardEvery = runningRef.current ? 2000 : SLOW_MS
        if (Date.now() - lastBoardAt.current >= boardEvery) await refreshBoard()
        setOnline(true)
        delay = runningRef.current ? FAST_MS : SLOW_MS
      } catch (e) {
        if (e instanceof ApiError && e.status === 0) {
          lastHealthAt.current = 0 // re-check health as soon as it comes back
          setOnline(false)
          delay = OFFLINE_MS
        } else {
          trouble = message(e)
          lastHealthAt.current = 0
        }
      }
      setProblem(trouble)
      if (!stopped) timer = setTimeout(tick, delay)
    }
    tick()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [pullEvents, refreshBoard])

  const run = useCallback(
    async (ticketId: number) => {
      if (startingRef.current) throw new ApiError(409, 'A run is already starting.')
      startingRef.current = true
      setStarting(true)
      try {
        const record = await api.run(ticketId)
        setFinished(null)
        runningRef.current = record
        setRunning(record)
        lastBoardAt.current = 0
        pullEvents().catch(() => {})
        return record
      } finally {
        startingRef.current = false
        setStarting(false)
      }
    },
    [pullEvents],
  )

  // After a human decision the money has moved: never report failure just because the follow-up refresh failed.
  const afterDecision = useCallback(
    async (result: DecisionResult) => {
      if (result.cash) setCash(result.cash)
      try {
        await Promise.all([refreshBoard(), pullEvents()])
      } catch (e) {
        setProblem(`Saved, but the board could not refresh: ${message(e)}`)
      }
      return result
    },
    [refreshBoard, pullEvents],
  )

  const approve = useCallback(
    async (approvalId: number, approvedBy: string, note = '') => afterDecision(await api.approve(approvalId, approvedBy, note)),
    [afterDecision],
  )
  const reject = useCallback(
    async (approvalId: number, decidedBy: string, note = '') => afterDecision(await api.reject(approvalId, decidedBy, note)),
    [afterDecision],
  )

  const reset = useCallback(async () => {
    await api.reset()
    setFinished(null)
    try {
      await Promise.all([refreshBoard(), pullEvents()])
    } catch (e) {
      setProblem(`Reset done, but the board could not refresh: ${message(e)}`)
    }
  }, [refreshBoard, pullEvents])

  // A ticket's older activity, if the first load's window did not reach it.
  const loadTicketHistory = useCallback(
    async (ticketId: number) => {
      const r = await api.events(0, 2000, ticketId)
      mergeEvents(r.events)
    },
    [mergeEvents],
  )

  return {
    online, problem, health, board, cash, approvals, events, running, starting, finished, boardVersion,
    run, approve, reject, reset, loadTicketHistory,
  }
}
