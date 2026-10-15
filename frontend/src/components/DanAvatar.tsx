export type DanMood = 'idle' | 'thinking' | 'happy'

interface Props {
  size?: number
  mood?: DanMood
  className?: string
}

/**
 * Dan, the Campus Customs bulldog, carried over from the HW 4 storefront: on
 * the desk he is the face of the Customer Service agent. Drawn in SVG so he
 * can blink, tilt his head while he works and pant when a draft is done
 * (animations in styles.css).
 */
export default function DanAvatar({ size = 56, mood = 'idle', className = '' }: Props) {
  return (
    <svg
      className={`dan dan--${mood} ${className}`}
      width={size}
      height={size}
      viewBox="0 0 120 120"
      aria-hidden="true"
      focusable="false"
    >
      <g className="dan__head">
        {/* Ears fold forward at the top corners of the head. */}
        <path
          className="dan__ear dan__ear--left"
          d="M30 30 C 16 22, 4 34, 8 50 C 16 50, 26 44, 36 36 Z"
          fill="#8a5a3b"
        />
        <path
          className="dan__ear dan__ear--right"
          d="M90 30 C 104 22, 116 34, 112 50 C 104 50, 94 44, 84 36 Z"
          fill="#8a5a3b"
        />

        {/* Broad head with heavy cheeks. */}
        <path
          d="M60 22 C 88 22, 104 38, 104 62 C 104 90, 86 104, 60 104 C 34 104, 16 90, 16 62 C 16 38, 32 22, 60 22 Z"
          fill="#dba878"
        />
        <path d="M46 34 q14 -6 28 0" stroke="#b07a4c" strokeWidth="2.4" fill="none" strokeLinecap="round" />
        <path d="M50 40 q10 -4 20 0" stroke="#b07a4c" strokeWidth="2.2" fill="none" strokeLinecap="round" />

        {/* White blaze down the face into the muzzle. */}
        <path
          d="M60 42 C 65 42, 67 52, 69 58 C 84 60, 94 70, 92 83 C 90 96, 76 102, 60 102 C 44 102, 30 96, 28 83 C 26 70, 36 60, 51 58 C 53 52, 55 42, 60 42 Z"
          fill="#fbf3e8"
        />
        <ellipse cx="79" cy="56" rx="11" ry="10" fill="#c48c5c" />

        <g className="dan__eyes">
          <circle cx="42" cy="56" r="6" fill="#2a1f1a" />
          <circle cx="78" cy="56" r="6" fill="#2a1f1a" />
          <circle className="dan__glint" cx="44" cy="54" r="2" fill="#fff" />
          <circle className="dan__glint" cx="80" cy="54" r="2" fill="#fff" />
        </g>

        <ellipse cx="34" cy="74" rx="6" ry="3.5" fill="#f2a7a0" opacity="0.55" />
        <ellipse cx="86" cy="74" rx="6" ry="3.5" fill="#f2a7a0" opacity="0.55" />

        <path d="M51 67 C 51 62, 69 62, 69 67 C 69 72, 63 75, 60 75 C 57 75, 51 72, 51 67 Z" fill="#2a1f1a" />
        <ellipse cx="56.5" cy="65.5" rx="2.6" ry="1.3" fill="#fff" opacity="0.55" />

        <path className="dan__tongue" d="M55 86 C 55 95, 65 95, 65 86 Z" fill="#e8737a" />
        <path
          d="M60 75 v5 M60 80 C 56 87, 45 87, 40 81 M60 80 C 64 87, 75 87, 80 81"
          stroke="#2a1f1a"
          strokeWidth="2.6"
          fill="none"
          strokeLinecap="round"
        />
        {/* The bulldog underbite: two lower teeth over the lip. */}
        <path d="M45 85 l2.8 -5.5 l2.8 5.5 Z" fill="#fff" stroke="#2a1f1a" strokeWidth="1.1" strokeLinejoin="round" />
        <path d="M69.4 85 l2.8 -5.5 l2.8 5.5 Z" fill="#fff" stroke="#2a1f1a" strokeWidth="1.1" strokeLinejoin="round" />
      </g>

      {/* Yale blue collar with a Y tag. */}
      <path d="M30 100 C 44 110, 76 110, 90 100 L 92 108 C 76 118, 44 118, 28 108 Z" fill="#00356b" />
      <g className="dan__tag">
        <circle cx="60" cy="113" r="6.5" fill="#63aaff" stroke="#fff" strokeWidth="1.4" />
        <text
          x="60"
          y="116.2"
          textAnchor="middle"
          fontSize="9"
          fontWeight="700"
          fill="#fff"
          fontFamily="Georgia, serif"
        >
          Y
        </text>
      </g>
    </svg>
  )
}
