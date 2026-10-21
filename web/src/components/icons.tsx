import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Base({ size = 16, children, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  )
}

export const MicIcon = (props: IconProps) => (
  <Base {...props}>
    <rect x="9" y="2" width="6" height="12" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0" />
    <path d="M12 18v4" />
  </Base>
)

export const MicOffIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M15 5a3 3 0 0 0-6 0v5" />
    <path d="M5 11a7 7 0 0 0 10.9 5.8M19 11v-1" />
    <path d="M12 18v4" />
    <path d="M3 3l18 18" />
  </Base>
)

export const SendIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 12l16-8-6 16-2-6-8-2z" />
  </Base>
)

export const StopIcon = (props: IconProps) => (
  <Base {...props}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </Base>
)

export const SpeakIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 9v6h4l5 4V5L8 9H4z" />
    <path d="M17 9a4 4 0 0 1 0 6" />
  </Base>
)

export const ChatIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M20 14a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z" />
  </Base>
)

export const FilmIcon = (props: IconProps) => (
  <Base {...props}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" />
  </Base>
)

export const MusicIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M9 18V6l10-2v12" />
    <circle cx="6.5" cy="18" r="2.5" />
    <circle cx="16.5" cy="16" r="2.5" />
  </Base>
)

export const GameIcon = (props: IconProps) => (
  <Base {...props}>
    <rect x="2.5" y="7" width="19" height="10" rx="4" />
    <path d="M7 11v2M6 12h2M15.5 11.5h.01M18 13.5h.01" />
  </Base>
)

export const CheckIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M4 12.5l5 5L20 6.5" />
  </Base>
)

export const AlertIcon = (props: IconProps) => (
  <Base {...props}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7.5v5.5M12 16.2v.3" />
  </Base>
)

export const SparkIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
  </Base>
)

export const RefreshIcon = (props: IconProps) => (
  <Base {...props}>
    <path d="M20 11a8 8 0 1 0-2.3 6.1" />
    <path d="M20 5v6h-6" />
  </Base>
)

export const SidekickMark = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
    <path
      d="M5 14.5c0-4.7 3.1-8.5 7-8.5s7 3.8 7 8.5"
      stroke="currentColor"
      strokeWidth={2.1}
      strokeLinecap="round"
    />
    <circle cx="12" cy="17" r="2.4" fill="currentColor" />
  </svg>
)
