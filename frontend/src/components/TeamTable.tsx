// The team table: five seats, with the Boss in the middle. Faint lines join
// every pair (any agent may ask any other). Lines the run actually used light up
// in the asker's colour and flow while the asker waits. An agent that is working
// rises off the table; one waiting on a teammate sinks into it; one that never
// got called stays a quiet hollow.

import { AGENTS, AGENT_BY_NAME, agentStates, delegationEdges } from '../agents'
import type { DeskEvent } from '../types'
import { AgentGlyph, AlertIcon, CheckIcon } from './Icons'

const PHASE_LABEL = { absent: 'Not called', working: 'Working', waiting: 'Waiting', done: 'Done', stopped: 'Stopped' } as const

export default function TeamTable({ events, live }: { events: DeskEvent[]; live: boolean }) {
  const states = agentStates(events)
  const edges = delegationEdges(events)
  const pairs = AGENTS.flatMap((a, i) => AGENTS.slice(i + 1).map((b) => [a, b] as const))
  const active = AGENTS.find((a) => states[a.name].phase === 'working')

  return (
    <section className="panel team" aria-labelledby="team-title">
      <header className="panel__head">
        <h2 id="team-title">The team table</h2>
        <span className="muted small">{live ? 'Live' : events.length ? 'Last run' : 'No run yet for this ticket'}</span>
      </header>
      <p className="sr-only" aria-live="polite">
        {live && active ? `${active.name}: ${states[active.name].doing}` : ''}
      </p>

      <div className="table-floor">
        <svg className="table-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {pairs.map(([a, b]) => (
            <line key={`${a.name}-${b.name}`} x1={a.seat.x} y1={a.seat.y} x2={b.seat.x} y2={b.seat.y} className="table-line" />
          ))}
          {edges.map((e) => {
            const a = AGENT_BY_NAME[e.from].seat
            const b = AGENT_BY_NAME[e.to].seat
            return (
              <line
                key={`${e.from}>${e.to}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                className={`handoff-line ${e.active && live ? 'handoff-line--flowing' : ''}`}
                style={{ stroke: `var(${AGENT_BY_NAME[e.from].colorVar})` }}
              />
            )
          })}
        </svg>

        {AGENTS.map((a) => {
          const s = states[a.name]
          const mood = a.name === 'Customer Service' ? (s.phase === 'working' ? 'thinking' : s.phase === 'done' ? 'happy' : 'idle') : undefined
          return (
            <article
              key={a.name}
              className={`seat seat--${s.phase} ${a.name === 'Boss' ? 'seat--boss' : ''}`}
              style={{ left: `${a.seat.x}%`, top: `${a.seat.y}%`, ['--agent' as string]: `var(${a.colorVar})` }}
              data-seat={a.name}
              aria-label={`${a.name}: ${PHASE_LABEL[s.phase]}. ${s.doing}`}
            >
              <div className="seat__disc" title={a.role}>
                <AgentGlyph agent={a.name} size={a.name === 'Boss' ? 30 : 26} mood={mood} />
                {s.phase === 'done' && (
                  <span className="seat__badge seat__badge--done" aria-hidden="true">
                    <CheckIcon size={12} />
                  </span>
                )}
                {s.phase === 'stopped' && (
                  <span className="seat__badge seat__badge--alert" aria-hidden="true">
                    <AlertIcon size={12} />
                  </span>
                )}
              </div>
              <div className="seat__name">{a.name}</div>
              <div className="seat__doing">{s.doing}</div>
            </article>
          )
        })}
      </div>
      <ul className="legend small" aria-label="How to read the table">
        <li><span className="legend__swatch legend__swatch--up" /> raised: speaking or working</li>
        <li><span className="legend__swatch legend__swatch--down" /> sunk: waiting on a teammate</li>
        <li><span className="legend__swatch legend__swatch--line" /> lit line: a handoff on this run</li>
      </ul>
    </section>
  )
}
