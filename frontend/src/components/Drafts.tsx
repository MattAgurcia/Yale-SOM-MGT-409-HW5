// Customer messages Dan (Customer Service) drafted for this ticket. They are
// letters on the desk, stamped DRAFT: nothing is ever sent by the agents.

import { useState } from 'react'
import { clock } from '../format'
import type { Draft } from '../types'
import { LetterIcon } from './Icons'

function Letter({ d }: { d: Draft }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`Subject: ${d.subject}\n\n${d.body}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      setCopied(false)
    }
  }
  return (
    <li className="letter">
      <span className="letter__stamp" aria-hidden="true">Draft · not sent</span>
      <p className="letter__to small">
        To <strong>{d.recipient}</strong> · draft {d.draft_id} · {clock(d.created_at)}
      </p>
      <h3 className="letter__subject">{d.subject}</h3>
      <p className="letter__body">{d.body}</p>
      <button type="button" className="btn btn--ghost btn--sm" onClick={copy}>
        {copied ? 'Copied' : 'Copy to send yourself'}
      </button>
    </li>
  )
}

export default function Drafts({ drafts }: { drafts: Draft[] }) {
  return (
    <section className="panel drafts" aria-labelledby="drafts-title">
      <header className="panel__head">
        <h2 id="drafts-title">
          <LetterIcon size={18} /> Letters for review
        </h2>
        <span className="muted small">{drafts.length}</span>
      </header>
      {drafts.length === 0 ? (
        <p className="muted small">No drafts on this ticket. When a customer needs a reply, Dan writes it here for you to check and send.</p>
      ) : (
        <ul className="letters">{[...drafts].reverse().map((d) => <Letter key={d.draft_id} d={d} />)}</ul>
      )}
    </section>
  )
}
