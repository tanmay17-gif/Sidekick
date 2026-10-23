import type { CSSProperties } from 'react'

/**
 * The Sidekick companion — Alexa-style glowing ring orb.
 *
 * No face. State is communicated purely through the ring:
 *   idle      → dim ring, slow breathe
 *   listening → cyan ring, expanding pulse waves
 *   thinking  → blue ring, rotating arc
 *   acting    → purple ring, fast pulse
 *   waiting   → amber ring, slow spin
 *   speaking  → cyan ring, wave ripples
 *   error     → red ring
 *   off / quiet → near-invisible ring
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
  size?: number
  label?: string
  className?: string
}

const STATE_TEXT: Record<CompanionState, string> = {
  off:       'Sidekick is switched off',
  idle:      'Sidekick is here when you need it',
  listening: 'Sidekick is listening',
  thinking:  'Sidekick is thinking',
  acting:    'Sidekick is working',
  waiting:   'Sidekick is waiting for you',
  speaking:  'Sidekick is speaking',
  quiet:     'Sidekick is staying quiet',
  error:     'Sidekick hit a problem',
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
          {/* Radial gradient for the sphere body — deep navy with a subtle inner highlight */}
          <radialGradient id="orb-body" cx="38%" cy="32%" r="65%">
            <stop offset="0%"   stopColor="#1e3a5f" />
            <stop offset="45%"  stopColor="#0a1a2e" />
            <stop offset="100%" stopColor="#040a12" />
          </radialGradient>

          {/* Glow ring gradient — used for the outer halo */}
          <radialGradient id="orb-halo" cx="50%" cy="50%" r="50%">
            <stop offset="60%" stopColor="var(--ring-color)" stopOpacity="0" />
            <stop offset="82%" stopColor="var(--ring-color)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--ring-color)" stopOpacity="0" />
          </radialGradient>

          {/* Clip to the sphere */}
          <clipPath id="orb-clip">
            <circle cx="100" cy="100" r="68" />
          </clipPath>
        </defs>

        {/* Outer ambient halo — breathes with state */}
        <circle className="companion__halo" cx="100" cy="100" r="96" fill="url(#orb-halo)" />

        {/* Pulse wave 1 — listening / speaking */}
        <circle className="companion__wave companion__wave--1" cx="100" cy="100" r="76" />

        {/* Pulse wave 2 — offset */}
        <circle className="companion__wave companion__wave--2" cx="100" cy="100" r="76" />

        {/* The sphere body */}
        <circle cx="100" cy="100" r="68" fill="url(#orb-body)" />

        {/* Inner top-left sheen — makes it look like a real sphere */}
        <ellipse cx="78" cy="72" rx="24" ry="16"
          fill="white" opacity="0.05"
          clipPath="url(#orb-clip)" />

        {/* The Alexa ring — glowing band at the equator of the sphere */}
        <circle className="companion__ring" cx="100" cy="100" r="68" />

        {/* Thinking arc — rotating, only visible in thinking state */}
        <g className="companion__arc">
          <path d="M100 28 A72 72 0 0 1 172 100" />
          <path d="M100 172 A72 72 0 0 1 28 100" />
        </g>

        {/* Waiting dashed ring — slow spin */}
        <circle className="companion__waiting-ring" cx="100" cy="100" r="80" />
      </svg>

      {label !== undefined ? <span className="companion__label">{label}</span> : null}

      <style>{`
        .companion {
          --companion-size: 92px;
          --ring-color: #00d4ff;
          display: inline-flex;
          flex-direction: column;
          align-items: center;
          gap: var(--space-2);
          width: var(--companion-size);
        }

        /* --- State ring colours --- */
        .companion[data-state='idle']      { --ring-color: #1a8fff; }
        .companion[data-state='listening'] { --ring-color: #00d4ff; }
        .companion[data-state='thinking']  { --ring-color: #1a8fff; }
        .companion[data-state='acting']    { --ring-color: #7c5fe6; }
        .companion[data-state='waiting']   { --ring-color: #ffaa33; }
        .companion[data-state='speaking']  { --ring-color: #00d4ff; }
        .companion[data-state='error']     { --ring-color: #ff5252; }
        .companion[data-state='quiet']     { --ring-color: #2a3550; }
        .companion[data-state='off']       { --ring-color: #141e2e; opacity: 0.4; }

        /* --- Art canvas --- */
        .companion__art {
          width: 100%;
          height: auto;
          overflow: visible;
          display: block;
        }

        /* --- Label --- */
        .companion__label {
          font-size: var(--text-2xs);
          letter-spacing: var(--tracking-wide);
          text-transform: uppercase;
          font-weight: 700;
          color: var(--ink-muted);
          text-align: center;
          line-height: 1.3;
        }

        /* --- Halo: ambient outer glow, always breathing --- */
        .companion__halo {
          transform-origin: 100px 100px;
          animation: orb-breathe 4s ease-in-out infinite;
        }

        /* --- The main ring: the Alexa-style edge ring --- */
        .companion__ring {
          fill: none;
          stroke: var(--ring-color);
          stroke-width: 3.5;
          opacity: 0.9;
          transform-origin: 100px 100px;
          filter: drop-shadow(0 0 6px var(--ring-color));
          animation: orb-ring-idle 4s ease-in-out infinite;
        }

        /* --- Pulse waves: expand outward from sphere edge --- */
        .companion__wave {
          fill: none;
          stroke: var(--ring-color);
          stroke-width: 1.5;
          opacity: 0;
          transform-origin: 100px 100px;
        }

        /* --- Thinking arcs --- */
        .companion__arc {
          fill: none;
          stroke: var(--ring-color);
          stroke-width: 3;
          stroke-linecap: round;
          opacity: 0;
          transform-origin: 100px 100px;
        }

        /* --- Waiting dashed ring --- */
        .companion__waiting-ring {
          fill: none;
          stroke: var(--ring-color);
          stroke-width: 1.5;
          stroke-dasharray: 8 14;
          stroke-linecap: round;
          opacity: 0;
          transform-origin: 100px 100px;
        }

        /* ================================================
           State-specific animations
           ================================================ */

        /* IDLE — ring gently pulses */
        .companion[data-state='idle'] .companion__ring {
          animation: orb-ring-idle 4s ease-in-out infinite;
        }

        /* LISTENING — cyan ring, two expanding wave pulses */
        .companion[data-state='listening'] .companion__ring {
          animation: orb-ring-bright 0.3s ease-out forwards;
          opacity: 1;
        }
        .companion[data-state='listening'] .companion__wave--1 {
          animation: orb-wave 2s ease-out infinite;
        }
        .companion[data-state='listening'] .companion__wave--2 {
          animation: orb-wave 2s ease-out 1s infinite;
        }

        /* THINKING — arc rotates */
        .companion[data-state='thinking'] .companion__arc {
          opacity: 1;
          animation: orb-spin 2s linear infinite;
        }
        .companion[data-state='thinking'] .companion__ring {
          opacity: 0.4;
          animation: orb-ring-idle 2s ease-in-out infinite;
        }

        /* ACTING — ring pulses fast, purple */
        .companion[data-state='acting'] .companion__ring {
          animation: orb-ring-pulse 1.2s ease-in-out infinite;
        }
        .companion[data-state='acting'] .companion__halo {
          animation: orb-breathe 1.2s ease-in-out infinite;
        }

        /* WAITING — dashed outer ring spins slowly */
        .companion[data-state='waiting'] .companion__waiting-ring {
          opacity: 0.7;
          animation: orb-spin 12s linear infinite;
        }
        .companion[data-state='waiting'] .companion__ring {
          opacity: 0.5;
        }

        /* SPEAKING — wave ripples + bright ring */
        .companion[data-state='speaking'] .companion__ring {
          animation: orb-ring-pulse 0.9s ease-in-out infinite;
          opacity: 1;
        }
        .companion[data-state='speaking'] .companion__wave--1 {
          animation: orb-wave 1.4s ease-out infinite;
        }
        .companion[data-state='speaking'] .companion__wave--2 {
          animation: orb-wave 1.4s ease-out 0.5s infinite;
        }

        /* ERROR — ring flashes red */
        .companion[data-state='error'] .companion__ring {
          animation: orb-ring-pulse 0.6s ease-in-out 3;
        }

        /* QUIET — dim ring, no animation */
        .companion[data-state='quiet'] .companion__ring {
          animation: none;
          opacity: 0.25;
        }
        .companion[data-state='quiet'] .companion__halo {
          animation: none;
          opacity: 0.1;
        }

        /* OFF */
        .companion[data-state='off'] .companion__ring  { opacity: 0.1; animation: none; }
        .companion[data-state='off'] .companion__halo  { animation: none; }

        /* ================================================
           Keyframes
           ================================================ */
        @keyframes orb-breathe {
          0%, 100% { transform: scale(1);    opacity: 0.7; }
          50%       { transform: scale(1.06); opacity: 1;   }
        }
        @keyframes orb-ring-idle {
          0%, 100% { opacity: 0.55; filter: drop-shadow(0 0 4px var(--ring-color)); }
          50%       { opacity: 0.9;  filter: drop-shadow(0 0 10px var(--ring-color)); }
        }
        @keyframes orb-ring-bright {
          to { opacity: 1; filter: drop-shadow(0 0 12px var(--ring-color)); }
        }
        @keyframes orb-ring-pulse {
          0%, 100% { opacity: 0.7;  filter: drop-shadow(0 0 5px var(--ring-color));  }
          50%       { opacity: 1;   filter: drop-shadow(0 0 16px var(--ring-color)); }
        }
        @keyframes orb-wave {
          0%   { transform: scale(1);    opacity: 0.6; }
          80%  { transform: scale(1.38); opacity: 0;   }
          100% { transform: scale(1.38); opacity: 0;   }
        }
        @keyframes orb-spin {
          to { transform: rotate(360deg); }
        }

        @media (prefers-reduced-motion: reduce) {
          .companion__ring,
          .companion__halo,
          .companion__wave,
          .companion__arc,
          .companion__waiting-ring {
            animation: none !important;
          }
        }
      `}</style>
    </div>
  )
}
