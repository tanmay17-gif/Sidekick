import type { CSSProperties } from 'react'

/**
 * The Sidekick companion.
 *
 * It is not a logo and it is not decoration: every visual property is bound
 * to a state the product is actually in - idle, listening, thinking, acting,
 * waiting, speaking, quiet or error. Motion explains the state change and it
 * stops entirely under `prefers-reduced-motion`.
 */

export type CompanionState =
  | 'off'
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'acting'
  | 'waiting'
  | 'speaking'
  | 'quiet'
  | 'error'

export interface CompanionProps {
  state: CompanionState
  /** Rendered size in pixels. */
  size?: number
  /** Optional short caption shown beside the companion. */
  label?: string
  className?: string
}

const STATE_TEXT: Record<CompanionState, string> = {
  off: 'Sidekick is switched off',
  idle: 'Sidekick is here when you need it',
  listening: 'Sidekick is listening',
  thinking: 'Sidekick is thinking',
  acting: 'Sidekick is working',
  waiting: 'Sidekick is waiting for you',
  speaking: 'Sidekick is speaking',
  quiet: 'Sidekick is staying quiet',
  error: 'Sidekick hit a problem',
}

export function Companion({ state, size = 92, label, className }: CompanionProps) {
  const style = { '--companion-size': `${size}px` } as CSSProperties

  return (
    <div
      className={`companion${className ? ` ${className}` : ''}`}
      data-state={state}
      style={style}
      role="img"
      aria-label={STATE_TEXT[state]}
    >
      <svg viewBox="0 0 200 200" className="companion__art" aria-hidden="true" focusable="false">
        <defs>
          <radialGradient id="companion-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--companion-glow)" stopOpacity="0.34" />
            <stop offset="58%" stopColor="var(--companion-glow)" stopOpacity="0.09" />
            <stop offset="100%" stopColor="var(--companion-glow)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="companion-body" x1="16%" y1="4%" x2="86%" y2="98%">
            <stop offset="0%" stopColor="var(--companion-light)" />
            <stop offset="52%" stopColor="var(--companion-mid)" />
            <stop offset="100%" stopColor="var(--companion-deep)" />
          </linearGradient>
          <clipPath id="companion-clip">
            <circle cx="100" cy="100" r="56" />
          </clipPath>
        </defs>

        {/* The halo breathes with the state. */}
        <circle className="companion__halo" cx="100" cy="100" r="92" fill="url(#companion-halo)" />

        {/* Listening rings show that the microphone is open. */}
        <g className="companion__rings">
          <circle cx="100" cy="100" r="62" />
          <circle cx="100" cy="100" r="62" />
        </g>

        {/* The waiting ring is dashed: it is asking for something. */}
        <circle className="companion__waiting" cx="100" cy="100" r="70" />

        {/* Thinking arcs rotate while the decision engine works. */}
        <g className="companion__arcs">
          <path d="M100 24 A76 76 0 0 1 176 100" />
          <path d="M100 176 A76 76 0 0 1 24 100" />
        </g>

        {/* Speaking waves. */}
        <g className="companion__waves">
          <circle cx="100" cy="100" r="72" />
          <circle cx="100" cy="100" r="82" />
        </g>

        {/* The body. */}
        <g className="companion__body">
          <circle cx="100" cy="100" r="56" fill="url(#companion-body)" />
          <ellipse cx="82" cy="78" rx="21" ry="15" fill="#ffffff" opacity="0.2" />
        </g>

        {/* Eyes. */}
        <g className="companion__eyes">
          <ellipse cx="84" cy="93" rx="8.4" ry="10" fill="#fffdf9" />
          <ellipse cx="116" cy="93" rx="8.4" ry="10" fill="#fffdf9" />
          <circle className="companion__pupil" cx="84" cy="93" r="4.4" fill="#241f1b" />
          <circle className="companion__pupil" cx="116" cy="93" r="4.4" fill="#241f1b" />
        </g>

        {/* A brow that appears while it waits for the user. */}
        <path className="companion__brow" d="M70 72 Q100 62 130 72" />

        {/* The mouth opens when Sidekick is speaking. */}
        <g clipPath="url(#companion-clip)">
          <ellipse className="companion__mouth" cx="100" cy="118" rx="14" ry="2.4" fill="#3a2118" />
        </g>
      </svg>

      {label !== undefined ? <span className="companion__label">{label}</span> : null}

      <style>{`
        .companion {
          --companion-size: 92px;
          --companion-glow: var(--accent);
          --companion-light: #8f8be6;
          --companion-mid: var(--accent);
          --companion-deep: var(--coral);
          display: inline-flex;
          flex-direction: column;
          align-items: center;
          gap: var(--space-2);
          width: var(--companion-size);
          transition: --companion-glow var(--duration-slow) linear;
        }
        .companion[data-state='error'] {
          --companion-glow: var(--state-danger);
          --companion-deep: #c2453a;
        }
        .companion[data-state='waiting'] {
          --companion-glow: var(--state-confirm);
          --companion-deep: #d98a3a;
        }
        .companion[data-state='quiet'] {
          --companion-glow: var(--ink-muted);
        }
        .companion[data-state='off'] {
          --companion-glow: var(--ink-faint);
          opacity: 0.5;
        }
        .companion__art {
          width: 100%;
          height: auto;
          overflow: visible;
          display: block;
        }
        .companion__label {
          font-size: var(--text-2xs);
          letter-spacing: var(--tracking-wide);
          text-transform: uppercase;
          font-weight: 700;
          color: var(--ink-muted);
          text-align: center;
          line-height: 1.3;
        }
        .companion__halo {
          transform-origin: 100px 100px;
          animation: companion-breathe 4.6s var(--ease-in-out) infinite;
        }
        .companion__body {
          transform-origin: 100px 100px;
          animation: companion-breathe 4.6s var(--ease-in-out) infinite;
        }
        .companion__rings,
        .companion__arcs,
        .companion__waves,
        .companion__waiting,
        .companion__brow {
          opacity: 0;
        }
        .companion__rings circle {
          fill: none;
          stroke: var(--accent);
          stroke-width: 2.4;
          transform-origin: 100px 100px;
        }
        .companion__arcs {
          fill: none;
          stroke: var(--state-thinking);
          stroke-width: 3;
          stroke-linecap: round;
          transform-origin: 100px 100px;
        }
        .companion__waves circle {
          fill: none;
          stroke: var(--coral);
          stroke-width: 2.4;
          transform-origin: 100px 100px;
        }
        .companion__waiting {
          fill: none;
          stroke: var(--state-confirm);
          stroke-width: 3;
          stroke-linecap: round;
          stroke-dasharray: 10 12;
          transform-origin: 100px 100px;
        }
        .companion__brow {
          fill: none;
          stroke: rgba(255, 255, 255, 0.85);
          stroke-width: 3.4;
          stroke-linecap: round;
        }
        .companion__mouth {
          transform-origin: 100px 118px;
        }

        .companion[data-state='listening'] .companion__rings { opacity: 1; }
        .companion[data-state='listening'] .companion__rings circle:first-child {
          animation: companion-ring 2s var(--ease-out) infinite;
        }
        .companion[data-state='listening'] .companion__rings circle:last-child {
          animation: companion-ring 2s var(--ease-out) 1s infinite;
        }
        .companion[data-state='listening'] .companion__halo { animation-duration: 2.2s; }

        .companion[data-state='thinking'] .companion__arcs {
          opacity: 1;
          animation: companion-spin 2.4s linear infinite;
        }
        .companion[data-state='thinking'] .companion__body {
          animation: companion-tilt 2.4s var(--ease-in-out) infinite;
        }

        .companion[data-state='acting'] .companion__body {
          animation: companion-work 900ms var(--ease-in-out) infinite;
        }
        .companion[data-state='acting'] .companion__halo {
          animation: companion-pulse 1.5s var(--ease-in-out) infinite;
        }

        .companion[data-state='waiting'] .companion__waiting {
          opacity: 1;
          animation: companion-spin 14s linear infinite;
        }
        .companion[data-state='waiting'] .companion__brow { opacity: 1; }

        .companion[data-state='speaking'] .companion__mouth {
          animation: companion-talk 420ms var(--ease-in-out) infinite;
        }
        .companion[data-state='speaking'] .companion__waves { opacity: 1; }
        .companion[data-state='speaking'] .companion__waves circle:first-child {
          animation: companion-wave 1.3s var(--ease-out) infinite;
        }
        .companion[data-state='speaking'] .companion__waves circle:last-child {
          animation: companion-wave 1.3s var(--ease-out) 0.45s infinite;
        }
        .companion[data-state='speaking'] .companion__body {
          animation: companion-breathe 1.8s var(--ease-in-out) infinite;
        }

        .companion[data-state='quiet'] .companion__halo { opacity: 0.35; }
        .companion[data-state='quiet'] .companion__mouth { transform: scaleY(0.4); }

        .companion[data-state='error'] .companion__body {
          animation: companion-shake 520ms var(--ease-out);
        }
        .companion[data-state='error'] .companion__brow { opacity: 1; }

        .companion[data-state='off'] .companion__body,
        .companion[data-state='off'] .companion__halo { animation: none; }

        @keyframes companion-breathe {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.03); }
        }
        @keyframes companion-pulse {
          0%, 100% { transform: scale(1); opacity: 0.85; }
          50% { transform: scale(1.08); opacity: 1; }
        }
        @keyframes companion-ring {
          0% { transform: scale(0.88); opacity: 0.8; }
          70% { transform: scale(1.24); opacity: 0; }
          100% { transform: scale(1.24); opacity: 0; }
        }
        @keyframes companion-wave {
          0% { transform: scale(0.9); opacity: 0.7; }
          70% { transform: scale(1.16); opacity: 0; }
          100% { transform: scale(1.16); opacity: 0; }
        }
        @keyframes companion-spin {
          to { transform: rotate(360deg); }
        }
        @keyframes companion-tilt {
          0%, 100% { transform: rotate(-3deg); }
          50% { transform: rotate(3deg); }
        }
        @keyframes companion-work {
          0%, 100% { transform: translateY(0) scale(1); }
          50% { transform: translateY(-4px) scale(1.02); }
        }
        @keyframes companion-talk {
          0%, 100% { transform: scaleY(0.5); }
          50% { transform: scaleY(3); }
        }
        @keyframes companion-shake {
          0%, 100% { transform: translateX(0); }
          25% { transform: translateX(-4px); }
          75% { transform: translateX(4px); }
        }

        @media (prefers-reduced-motion: reduce) {
          .companion__halo,
          .companion__body,
          .companion__rings circle,
          .companion__arcs,
          .companion__waves circle,
          .companion__waiting,
          .companion__mouth {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  )
}
