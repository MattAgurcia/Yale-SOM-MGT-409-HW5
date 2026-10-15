// Small shared pieces: status chip, agent disc, animated number, confirm dialog.

import { useEffect, useRef, useState } from 'react'
import { AGENT_BY_NAME } from '../agents'
import { statusLook } from '../format'
import type { AgentName } from '../types'
import type { DanMood } from './DanAvatar'
import { AgentGlyph, AlertIcon, CheckIcon, DotIcon, FlagIcon, HandIcon, SpinIcon } from './Icons'

export function StatusChip({ status, running = false, compact = false, pending }: { status: string; running?: boolean; compact?: boolean; pending?: number }) {
  const look = statusLook(status, running, pending)
  const Icon = { dot: DotIcon, spin: SpinIcon, hand: HandIcon, check: CheckIcon, alert: AlertIcon, flag: FlagIcon }[look.icon]
  return (
    <span className={`chip chip--${look.tone} ${compact ? 'chip--compact' : ''}`}>
      <Icon size={compact ? 13 : 15} />
      {look.label}
    </span>
  )
}

/** An agent's identity: a soft disc in the agent's colour with its glyph. Colour never stands alone: the name is always shown nearby. */
export function AgentDisc({ agent, size = 40, mood }: { agent: AgentName; size?: number; mood?: DanMood }) {
  const meta = AGENT_BY_NAME[agent]
  return (
    <span className="agent-disc" style={{ width: size, height: size, ['--agent' as string]: `var(${meta.colorVar})` }} aria-hidden="true">
      <AgentGlyph agent={agent} size={Math.round(size * 0.5)} mood={mood} />
    </span>
  )
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** A number that rolls to its new value (instantly for reduced motion). */
export function useRollingNumber(value: number, ms = 900): number {
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  useEffect(() => {
    // Hidden tabs get no animation frames, so jump straight to the value there.
    if (prefersReducedMotion() || document.hidden || from.current === value) {
      from.current = value
      setShown(value)
      return
    }
    const start = performance.now()
    const a = from.current
    let frame = 0
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms)
      const eased = 1 - Math.pow(1 - t, 3)
      setShown(a + (value - a) * eased)
      if (t < 1) frame = requestAnimationFrame(step)
      else from.current = value
    }
    frame = requestAnimationFrame(step)
    // If the tab goes hidden mid-roll, frames stop; land on the true value anyway.
    const settle = setTimeout(() => {
      cancelAnimationFrame(frame)
      from.current = value
      setShown(value)
    }, ms + 150)
    return () => {
      cancelAnimationFrame(frame)
      clearTimeout(settle)
      from.current = value
    }
  }, [value, ms])
  return shown
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  tone = 'primary',
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string
  body: React.ReactNode
  confirmLabel: string
  tone?: 'primary' | 'danger'
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  // A native modal <dialog>: it traps focus and makes the desk behind it inert.
  // Focus starts on Cancel (the safe choice) once, on open, and is never pulled
  // back on later re-renders; on close it returns to whatever opened the dialog.
  const ref = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef(onCancel)
  cancelRef.current = onCancel
  useEffect(() => {
    const dialog = ref.current
    const opener = document.activeElement as HTMLElement | null
    dialog?.showModal()
    dialog?.querySelector<HTMLButtonElement>('.dialog__cancel')?.focus()
    const onEscape = (e: Event) => {
      e.preventDefault()
      cancelRef.current()
    }
    dialog?.addEventListener('cancel', onEscape)
    return () => {
      dialog?.removeEventListener('cancel', onEscape)
      if (dialog?.open) dialog.close()
      setTimeout(() => {
        if (opener && opener.isConnected) opener.focus()
      }, 0)
    }
  }, [])
  return (
    <dialog ref={ref} className="dialog" aria-labelledby="dialog-title" onClick={(e) => e.target === ref.current && !busy && onCancel()}>
      <h2 id="dialog-title">{title}</h2>
      <div className="dialog__body">{body}</div>
      <div className="dialog__actions">
        <button type="button" className="btn btn--ghost dialog__cancel" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" className={`btn ${tone === 'danger' ? 'btn--danger' : 'btn--primary'}`} onClick={onConfirm} disabled={busy} aria-busy={busy}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
