import type { CSSProperties } from 'react'

/**
 * The Sidekick companion.
 *
 * It is not decoration: every visual property is bound to a real state the
 * product is actually in - listening, thinking, acting, waiting for the user,
 * speaking, quiet or disconnected. Motion is used only to explain a state
 * change, and it stops entirely under `prefers-reduced-motion`.
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
  /** Moves the eyes and the body slightly - used to show attention. */
  attention?: number
}

const STATE_TEXT: Record<CompanionState, string> = {
  off: 'off',
  idle: 'here when you need me',
  listening: 'listening',
  thinking: 'thinking it over',
  acting: 'working on it',
  waiting: 'waiting for you',
  speaking: 'talking',
  quiet: 'staying quiet',
  error: 'something went wrong',
}

export function Companion({
  state,
  size = 92,
  label,
  className,
  attention = 0,
}: CompanionProps) {
  const look = Math.max(-1, Math.min(1, attention))
  const style = {
    '--companion-size': `${size}px`,
    '--companion-look': `${look * 2.4}px`,
  } as CSSProperties

  return (
    <div
      className={`companion${className ? ` ${className}` : ''}`}
      data-state={state}
      style={style}
      role="img"
      aria-label={`Sidekick is ${STATE_TEXT[state]}`}
    >
      <svg viewBox="0 0 120 120" className="companion__art" aria-hidden="true" focusable="false">
        <defs>
          <radialGradient id="companion-halo" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.28" />
            <stop offset="62%" stopColor="var(--accent)" stopOpacity="0.07" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </radialGradient>
          <linearGradient id="companion-body" x1="18%" y1="6%" x2="86%" y2="96%">
            <stop offset="0%" stopColor="var(--accent-strong)" />
            <stop offset="58%" stopColor="var(--accent)" />
            <stop offset="100%" stopColor="var(--coral)" />
          </linearGradient>
          <clipPath id="companion-clip">
            <circle cx="60" cy="60" r="34" />
          </clipPath>
        </defs>

        {/* The halo breathes with the state. */}
        <circle className="companion__halo" cx="60" cy="60" r="54" fill="url(#companion-halo)" />

        {/* Listening rings show that the microphone is open. */}
        <g className="companion__rings">
          <circle cx="60" cy="60" r="38" />
          <circle cx="60" cy="60" r="38" />
        </g>

        {/* Thinking arcs rotate while the decision engine works. */}
        <g className="companion__arcs">
          <path d="M60 16 A44 44 0 0 1 104 60" />
          <path d="M60 104 A44 44 0 0 1 16 60" />
        </g>

        {/* The body. */}
        <g className="companion__body">
          <circle cx="60" cy="60" r="34" fill="url(#companion-body)" />
          <circle cx="49" cy="46" r="13" fill="#ffffff" opacity="0.16" />
        </g>

        {/* Eyes. */}
        <g className="companion__eyes">
          <ellipse cx="49" cy="55" rx="5.2" ry="6.2" fill="#fffdf9" />
          <ellipse cx="71" cy="55" rx="5.2" ry="6.2" fill="#fffdf9" />
          <circle className="companion__pupil" cx="49" cy="55" r="2.7" fill="#241f1b" />
          <circle className="companion__pupil" cx="71" cy="55" r="2.7" fill="#241f1b" />
        </g>

        {/* A brow line that appears while it waits for the user. */}
        <path className="companion__brow" d="M42 42 Q60 36 78 42" />

        {/* The mouth opens when Sidekick is speaking. */}
        <g clipPath="url(#companion-clip)">
          <ellipse className="companion__mouth" cx="60" cy="72" rx="9" ry="1.6" fill="#3a2118" />
        </g>
      </svg>

      {label !== undefined ? (
        <span className="companion__label">{label}</span>
      ) : null}

      <style>{`
        .companion {
          --companion-size: 92px;
          display: inline-flex;
          flex-direction: column;
          align-items: center;
          gap: var(--space-2);
          width: var(--companion-size);
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
          font-weight: 600;
          color: var(--ink-muted);
          text-align: center;
          line-height: 1.3;
        }
        .companion__halo {
          transform-origin: 60px 60px;
          animation: companion-breathe 4.6s var(--ease-in-out) infinite;
        }
        .companion__body {
          transform-origin: 60px 60px;
          animation: companion-breathe 4.6s var(--ease-in-out) infinite;
        }
        .companion__rings {
          opacity: 0;
        }
        .companion__rings circle {
          fill: none;
          stroke: var(--accent);
          stroke-width: 1.6;
          transform-origin: 60px 60px;
        }
        .companion__arcs {
          opacity: 0;
          fill: none;
          stroke: var(--state-thinking);
          stroke-width: 2;
          stroke-linecap: round;
        }
        .companion__brow {
          fill: none;
          stroke: rgba(255, 255, 255, 0.8);
          stroke-width: 2.2;
          stroke-linecap: round;
          opacity: 0;
        }
        .companion__mouth {
          transform-origin: 60px 72px;
        }
        .companion__pupil {
          transition: transform var(--duration-base) var(--ease-out);
          transform: translateX(var(--companion-look, 0px));
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
          transform-origin: 60px 60px;
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

        .companion[data-state='waiting'] .companion__brow { opacity: 1; }
        .companion[data-state='waiting'] .companion__halo {
          animation: companion-breathe 3.4s var(--ease-in-out) infinite;
        }

        .companion[data-state='speaking'] .companion__mouth {
          animation: companion-talk 420ms var(--ease-in-out) infinite;
        }
        .companion[data-state='speaking'] .companion__body {
          animation: companion-breathe 1.8s var(--ease-in-out) infinite;
        }

        .companion[data-state='quiet'] .companion__halo { opacity: 0.4; }
        .companion[data-state='quiet'] .companion__mouth { transform: scaleY(0.4); }

        .companion[data-state='error'] .companion__body { animation: companion-shake 520ms var(--ease-out); }
        .companion[data-state='error'] .companion__brow { opacity: 1; }
        .companion[data-state='off'] { opacity: 0.45; }
        .companion[data-state='off'] .companion__body,
        .companion[data-state='off'] .companion__halo { animation: none; }

        @keyframes companion-breathe {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.035); }
        }
        @keyframes companion-pulse {
          0%, 100% { transform: scale(1); opacity: 0.85; }
          50% { transform: scale(1.09); opacity: 1; }
        }
        @keyframes companion-ring {
          0% { transform: scale(0.86); opacity: 0.75; }
          70% { transform: scale(1.22); opacity: 0; }
          100% { transform: scale(1.22); opacity: 0; }
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
          50% { transform: translateY(-3px) scale(1.02); }
        }
        @keyframes companion-talk {
          0%, 100% { transform: scaleY(0.5); }
          50% { transform: scaleY(2.6); }
        }
        @keyframes companion-shake {
          0%, 100% { transform: translateX(0); }
          25% { transform: translateX(-3px); }
          75% { transform: translateX(3px); }
        }

        @media (prefers-reduced-motion: reduce) {
          .companion__halo,
          .companion__body,
          .companion__rings circle,
          .companion__arcs,
          .companion__mouth {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  )
}
