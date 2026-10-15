// Small line icons (24px grid, currentColor) and each agent's glyph.

import type { AgentName } from '../types'
import DanAvatar, { type DanMood } from './DanAvatar'

interface IconProps {
  size?: number
  className?: string
}

const Svg = ({ size = 18, className = '', children }: IconProps & { children: React.ReactNode }) => (
  <svg
    className={`icon ${className}`}
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.8}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    {children}
  </svg>
)

export const CheckIcon = (p: IconProps) => <Svg {...p}><path d="M5 12.5l4.2 4.2L19 7" /></Svg>
export const HandIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 13V6.5a1.5 1.5 0 0 1 3 0V12M11 11V5a1.5 1.5 0 0 1 3 0v6M14 11V6.5a1.5 1.5 0 0 1 3 0V14c0 3.9-2.6 6-6 6-2.6 0-4-1.4-5.4-3.6L4 13.8a1.4 1.4 0 0 1 2.3-1.6L8 14" />
  </Svg>
)
export const AlertIcon = (p: IconProps) => (
  <Svg {...p}><path d="M12 4l9 16H3L12 4z" /><path d="M12 10v4M12 17v.01" /></Svg>
)
export const FlagIcon = (p: IconProps) => <Svg {...p}><path d="M6 21V4M6 4.5h11l-2.5 4 2.5 4H6" /></Svg>
export const DotIcon = (p: IconProps) => <Svg {...p}><circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" /></Svg>
export const SpinIcon = (p: IconProps) => (
  <Svg {...p} className={`spin ${p.className ?? ''}`}><path d="M12 3a9 9 0 1 0 9 9" /></Svg>
)
export const PlayIcon = (p: IconProps) => <Svg {...p}><path d="M8 5.5v13l11-6.5-11-6.5z" fill="currentColor" /></Svg>
export const ResetIcon = (p: IconProps) => (
  <Svg {...p}><path d="M4 12a8 8 0 1 0 2.4-5.7" /><path d="M4 4v4.5h4.5" /></Svg>
)
export const PersonIcon = (p: IconProps) => (
  <Svg {...p}><circle cx="12" cy="8" r="3.5" /><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" /></Svg>
)
export const ToolIcon = (p: IconProps) => (
  <Svg {...p}><path d="M14.5 6.5a4 4 0 0 0-5.3 5.2L4 17l3 3 5.3-5.2a4 4 0 0 0 5.2-5.3L15 12l-3-3 2.5-2.5z" /></Svg>
)
export const ArrowIcon = (p: IconProps) => <Svg {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Svg>
export const LetterIcon = (p: IconProps) => (
  <Svg {...p}><rect x="3.5" y="5.5" width="17" height="13" rx="2" /><path d="M4 7l8 6 8-6" /></Svg>
)
export const VaultIcon = (p: IconProps) => (
  <Svg {...p}><rect x="3.5" y="4.5" width="17" height="15" rx="2.5" /><circle cx="12" cy="12" r="3.5" /><path d="M12 8.5V7M12 17v-1.5M15.5 12H17M7 12h1.5" /></Svg>
)
export const KeyIcon = (p: IconProps) => (
  <Svg {...p}><circle cx="8" cy="15" r="4" /><path d="M11 12l8-8M16 7l2 2M14 9l2 2" /></Svg>
)

/** The Boss: a compass, because it points the team. */
const BossGlyph = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M14.8 9.2l-1.7 5-3.9 1.6 1.7-5 3.9-1.6z" fill="currentColor" />
  </Svg>
)
/** Inventory: a stock box. */
const InventoryGlyph = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 7.5L12 3.5l8.5 4v9L12 20.5l-8.5-4v-9z" />
    <path d="M3.5 7.5L12 11.5l8.5-4M12 11.5v9" />
  </Svg>
)
/** Accounting: a stack of coins. */
const AccountingGlyph = (p: IconProps) => (
  <Svg {...p}>
    <ellipse cx="12" cy="6.5" rx="6.5" ry="2.5" />
    <path d="M5.5 6.5v4c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-4M5.5 10.5v4c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-4M5.5 14.5v3c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-3" />
  </Svg>
)
/** Facilities: the Chapel Street storefront. */
const FacilitiesGlyph = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 10.5V20h16v-9.5M2.5 10.5l2-6h15l2 6z" />
    <path d="M9.5 20v-5.5h5V20" />
  </Svg>
)

export function AgentGlyph({ agent, size = 22, mood = 'idle' }: { agent: AgentName; size?: number; mood?: DanMood }) {
  switch (agent) {
    case 'Boss':
      return <BossGlyph size={size} />
    case 'Inventory':
      return <InventoryGlyph size={size} />
    case 'Accounting':
      return <AccountingGlyph size={size} />
    case 'Facilities':
      return <FacilitiesGlyph size={size} />
    case 'Customer Service':
      return <DanAvatar size={size * 1.55} mood={mood} />
  }
}
