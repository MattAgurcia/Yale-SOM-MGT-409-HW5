// What the team is saying and doing, step by step, from the audit trail.
// Each agent writes in its own colour lane; handoffs read as "A → B" notes,
// tool calls as one-line findings, and each agent's report as a speech card.

import { useEffect, useRef, useState } from 'react'
import { didVerb, isAgent, toolGist } from '../agents'
import { clock } from '../format'
import type { AgentName, DeskEvent } from '../types'
import { AgentDisc } from './bits'
import { AlertIcon, ArrowIcon, PersonIcon, ResetIcon, ToolIcon } from './Icons'

const lane = (agent: AgentName) => ({ ['--agent' as string]: `var(--agent-${agent === 'Customer Service' ? 'cs' : agent.toLowerCase()})` })

function Clamp({ text, lines = 4 }: { text: string; lines?: number }) {
  const [open, setOpen] = useState(false)
  const long = text.length > lines * 90
  return (
    <div>
      <p className={`clamp ${open ? '' : `clamp--${lines}`}`}>{text}</p>
      {long && (
        <button type="button" className="linkish small" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? 'Show less' : 'Show all'}
        </button>
      )}
    </div>
  )
}

function Row({ e }: { e: DeskEvent }) {
  const time = <time className="feed__time" dateTime={e.ts}>{clock(e.ts)}</time>
  switch (e.event) {
    case 'run_start':
      return <li className="feed__divider">{time} Run started</li>
    case 'run_end': {
      const u = e.detail.usage as { requests?: number; total_tokens?: number } | undefined
      return (
        <li className="feed__divider">
          {time} Run {String(e.detail.stop_reason)}
          {u ? ` · ${u.requests} model calls · ${Math.round((u.total_tokens ?? 0) / 1000)}k tokens` : ''}
        </li>
      )
    }
    case 'db_reset':
      return (
        <li className="feed__divider feed__divider--reset">
          {time} <ResetIcon size={14} /> Shop data reset to the original
        </li>
      )
    case 'delegation':
      if (!isAgent(e.agent)) return null
      return (
        <li className="feed__item feed__handoff" style={lane(e.agent)}>
          <AgentDisc agent={e.agent} size={30} />
          <div className="feed__body">
            <div className="feed__who">
              {e.agent} <ArrowIcon size={14} /> {String(e.detail.to)} {time}
            </div>
            <Clamp text={String(e.detail.request ?? '')} lines={3} />
          </div>
        </li>
      )
    case 'tool_call': {
      if (!isAgent(e.agent) || e.tools[0] === 'ask_agent') return null
      const ok = e.detail.status === 'ok'
      const gist = ok ? toolGist(e.tools[0], e.detail.result, e.detail.args) : String(e.detail.error ?? 'refused').replace(/^\w+Error: /, '')
      return (
        <li className={`feed__item feed__tool ${ok ? '' : 'feed__tool--refused'}`} style={lane(e.agent)}>
          <AgentDisc agent={e.agent} size={22} />
          <div className="feed__body">
            <div className="feed__who">
              {e.agent} {ok ? didVerb(e.tools[0]) : 'was refused'}
              <code className="feed__raw" title="the MCP tool">
                <ToolIcon size={11} /> {e.tools[0]}
              </code>
              {!ok && (
                <span className="tag tag--alert">
                  <AlertIcon size={12} /> refused
                </span>
              )}
              {time}
            </div>
            {gist && <p className="feed__gist">{gist}</p>}
          </div>
        </li>
      )
    }
    case 'call_refused':
      if (!isAgent(e.agent)) return null
      return (
        <li className="feed__item feed__tool feed__tool--refused" style={lane(e.agent)}>
          <AgentDisc agent={e.agent} size={22} />
          <div className="feed__body">
            <div className="feed__who">
              {e.agent} tried <code className="feed__raw">{e.tools[0]}</code>
              <span className="tag tag--alert">
                <AlertIcon size={12} /> not allowed
              </span>
              {time}
            </div>
            <p className="feed__gist">{(e.said ?? '').slice(0, 220)}</p>
          </div>
        </li>
      )
    case 'model_step':
      if (!isAgent(e.agent) || !e.said || e.said.trim().startsWith('{')) return null
      return (
        <li className="feed__item feed__thought" style={lane(e.agent)}>
          <span className="feed__lane" aria-hidden="true" />
          <div className="feed__body">
            <div className="feed__who">{e.agent} {time}</div>
            <Clamp text={e.said} lines={2} />
          </div>
        </li>
      )
    case 'agent_end':
      if (!isAgent(e.agent) || !e.said) return null
      return (
        <li className={`feed__item feed__report ${e.agent === 'Boss' && e.depth === 0 ? 'feed__report--boss' : ''}`} style={lane(e.agent)}>
          <AgentDisc agent={e.agent} size={34} mood="happy" />
          <div className="feed__body bubble">
            <div className="feed__who">
              {e.agent} {e.agent === 'Boss' && e.depth === 0 ? 'decides' : 'reports'} {time}
            </div>
            <Clamp text={e.said} lines={5} />
          </div>
        </li>
      )
    case 'human_decision':
      return (
        <li className={`feed__item feed__human ${e.detail.outcome === 'refused' ? 'feed__human--refused' : ''}`}>
          <span className="human-disc" aria-hidden="true"><PersonIcon size={16} /></span>
          <div className="feed__body">
            <div className="feed__who">You (as {String(e.detail.decided_by)}) {time}</div>
            <p className="feed__gist">{e.said}</p>
          </div>
        </li>
      )
    default:
      return null
  }
}

export default function ActivityFeed({
  events,
  scope,
  onScope,
  live,
  ticketId,
}: {
  events: DeskEvent[]
  scope: 'run' | 'all'
  onScope: (s: 'run' | 'all') => void
  live: boolean
  ticketId: number
}) {
  const box = useRef<HTMLOListElement>(null)
  const stick = useRef(true)
  useEffect(() => {
    const el = box.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [events.length])

  return (
    <section className="panel feed" aria-labelledby="feed-title">
      <header className="panel__head">
        <h2 id="feed-title">What the team is saying</h2>
        <div className="seg" role="group" aria-label="Which activity to show">
          <button type="button" aria-pressed={scope === 'run'} onClick={() => onScope('run')}>
            Latest run
          </button>
          <button type="button" aria-pressed={scope === 'all'} onClick={() => onScope('all')}>
            Everything on #{ticketId}
          </button>
        </div>
      </header>
      <ol
        className="feed__list"
        ref={box}
        onScroll={(ev) => {
          const el = ev.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
        }}
        aria-label="Activity, oldest first"
      >
        {events.length === 0 && <li className="feed__empty muted">No activity yet. Press Run and the team's conversation appears here.</li>}
        {events.map((e) => (
          <Row key={e.seq} e={e} />
        ))}
        {live && (
          <li className="feed__typing" aria-hidden="true">
            <span /> <span /> <span />
          </li>
        )}
      </ol>
    </section>
  )
}
