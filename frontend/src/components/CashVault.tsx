// Checking balance: the one hero number on the desk, a meter of what is left of
// the starting cash, and what pending requests would take. When a payment is
// approved the number rolls down and the amount drops out of the vault.

import { useEffect, useRef, useState } from 'react'
import { money } from '../format'
import type { Cash } from '../types'
import { useRollingNumber } from './bits'
import { AlertIcon, VaultIcon } from './Icons'

const KIND: Record<string, string> = { invoice: 'Invoice', rent: 'Rent', purchase_order: 'Purchase order' }

export default function CashVault({ cash }: { cash: Cash | null }) {
  const balance = cash?.balance ?? 0
  const shown = useRollingNumber(balance)
  const prev = useRef<number | null>(null)
  const [drops, setDrops] = useState<{ id: number; amount: number }[]>([])

  useEffect(() => {
    if (prev.current !== null && balance < prev.current) {
      const drop = { id: Date.now(), amount: prev.current - balance }
      setDrops((d) => [...d, drop])
      setTimeout(() => setDrops((d) => d.filter((x) => x.id !== drop.id)), 2600)
    }
    prev.current = balance
  }, [balance])

  if (!cash) {
    return (
      <section className="panel vault" aria-busy="true">
        <h2>Checking balance</h2>
        <p className="muted">Loading…</p>
      </section>
    )
  }

  const paid = cash.payments.reduce((s, p) => s + p.amount, 0)
  const start = balance + paid // no revenue comes in, so start = now + everything paid
  const pct = (n: number) => (start > 0 ? Math.max(0, Math.min(100, (n / start) * 100)) : 0)
  const pendingCovered = Math.min(cash.pending_total, balance)
  const short = cash.pending_total - balance

  return (
    <section className="panel vault" aria-labelledby="vault-title">
      <header className="panel__head">
        <h2 id="vault-title">
          <VaultIcon size={18} /> Checking balance
        </h2>
        <span className="muted small">as of {cash.as_of}</span>
      </header>

      <div className="vault__hero">
        <span className="hero-figure" aria-hidden="true">
          {money(shown)}
        </span>
        <span className="sr-only" role="status">
          Checking balance {money(balance)}
        </span>
        {drops.map((d) => (
          <span key={d.id} className="vault__drop" aria-hidden="true">
            −{money(d.amount)}
          </span>
        ))}
      </div>

      <div
        className="meter"
        role="img"
        aria-label={`${money(balance)} left of ${money(start)}; ${money(cash.pending_total)} waiting on approval`}
      >
        <div className="meter__fill" style={{ width: `${pct(balance)}%` }} title={`Left: ${money(balance)}`}>
          {pendingCovered > 0 && (
            <div
              className="meter__pending"
              style={{ width: `${(pendingCovered / Math.max(balance, 1)) * 100}%` }}
              title={`Waiting on approval: ${money(cash.pending_total)}`}
            />
          )}
        </div>
      </div>
      <div className="meter__scale small muted">
        <span>$0</span>
        <span>started at {money(start)}</span>
      </div>
      <p className="meter__key small">
        <span className="meter__swatch meter__swatch--left" aria-hidden="true" /> left in checking
        <span className="meter__swatch meter__swatch--pending" aria-hidden="true" /> {short > 0 ? 'all of it is asked for' : 'asked for, waiting on you'}
      </p>

      <dl className="vault__stats">
        <div>
          <dt>Paid out</dt>
          <dd>{money(paid)}</dd>
        </div>
        <div>
          <dt>Waiting on you</dt>
          <dd>{money(cash.pending_total)}</dd>
        </div>
        <div>
          <dt>If all approved</dt>
          <dd className={short > 0 ? 'neg' : ''}>{money(cash.balance_if_all_pending_paid)}</dd>
        </div>
      </dl>

      {short > 0 && (
        <p className="note note--alert" role="note">
          <AlertIcon size={16} /> The requests waiting on you add up to {money(short)} more than checking holds. Approve in order of
          priority; the pay step refuses anything that would take cash below zero.
        </p>
      )}

      <details className="ledger">
        <summary>
          Ledger <span className="muted">({cash.payments.length} payment{cash.payments.length === 1 ? '' : 's'})</span>
        </summary>
        {cash.payments.length === 0 ? (
          <p className="muted small">No money has left the shop yet. Every payment needs your approval.</p>
        ) : (
          <table className="ledger__table">
            <thead>
              <tr>
                <th scope="col">What</th>
                <th scope="col">Approved by</th>
                <th scope="col" className="num">Amount</th>
              </tr>
            </thead>
            <tbody>
              {cash.payments.map((p) => (
                <tr key={p.payment_id}>
                  <td>
                    {KIND[p.kind] ?? p.kind} {p.ref_id}
                    <span className="muted small"> · {p.paid_at}</span>
                  </td>
                  <td>{p.approved_by}</td>
                  <td className="num">−{money(p.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </details>
    </section>
  )
}
