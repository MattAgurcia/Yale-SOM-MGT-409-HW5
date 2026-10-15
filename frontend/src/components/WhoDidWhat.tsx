// A short summary of what each agent did on the ticket since the last reset
// (every run, so a final Boss-only "close" run never hides the real work): who
// asked it, whom it asked, what it checked, what it filed, and its last words.

import { AGENT_BY_NAME, agentSummaries, didVerb } from '../agents'
import type { DeskEvent } from '../types'
import { AgentDisc } from './bits'
import { AlertIcon } from './Icons'

export default function WhoDidWhat({ events }: { events: DeskEvent[] }) {
  const all = agentSummaries(events)
  const involved = all.filter((s) => s.involved)
  const absent = all.filter((s) => !s.involved)
  const runs = new Set(events.filter((e) => e.event === 'run_start').map((e) => e.run_id)).size

  return (
    <section className="panel who" aria-labelledby="who-title">
      <header className="panel__head">
        <h2 id="who-title">Who did what</h2>
        <span className="muted small">{runs ? `${runs} run${runs > 1 ? 's' : ''} on this ticket` : ''}</span>
      </header>
      {involved.length === 0 ? (
        <p className="muted small">Run the team and each agent's part shows up here.</p>
      ) : (
        <ul className="who__list">
          {involved.map((s) => (
            <li key={s.agent} className="who__card" style={{ ['--agent' as string]: `var(${AGENT_BY_NAME[s.agent].colorVar})` }}>
              <div className="who__head">
                <AgentDisc agent={s.agent} size={30} />
                <div>
                  <strong>{s.agent}</strong>
                  <div className="muted small">
                    {s.askedBy.length ? `asked by ${s.askedBy.join(', ')}` : 'took the ticket'}
                    {s.asked.length ? ` · asked ${s.asked.join(', ')}` : ''}
                    {runs > 1 ? ` · on ${s.runs} of ${runs} runs` : ''}
                  </div>
                </div>
              </div>
              {s.tools.length > 0 && (
                <ul className="who__tools" aria-label={`What ${s.agent} did`}>
                  {s.tools.map((t) => (
                    <li key={t.tool} className={t.errors ? 'refused' : ''} title={t.tool}>
                      {didVerb(t.tool)}
                      {t.count > 1 ? ` ×${t.count}` : ''}
                      {t.errors > 0 && (
                        <span className="who__refused">
                          <AlertIcon size={12} /> {t.errors} refused
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {s.writes.length > 0 && (
                <ul className="who__writes small">
                  {s.writes.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              )}
              {s.finalWords && <p className="who__words small clamp clamp--3">{s.finalWords}</p>}
            </li>
          ))}
        </ul>
      )}
      {involved.length > 0 && absent.length > 0 && (
        <p className="muted small">Not called on this ticket: {absent.map((s) => s.agent).join(', ')}.</p>
      )}
    </section>
  )
}
