# Sidekick web client

The browser surface of Sidekick: voice in, decision engine out, real outcomes on
screen. This package is owned by **Agent 3 (Product Experience)**.

```
web/
  src/
    lib/api/          contract v1 client, types, error normalisation
    lib/voice/        Web Speech recognition + synthesis wrappers
    lib/media/        subtitle parsing, cue lookup, companion events
    lib/games/        FEN rendering helpers
    state/            the conversation state machine
    components/       the interface
  dev/stub-server.mjs SIMULATED_TEST_ONLY development backend
  tests/unit/         unit + integration tests (Vitest)
  tests/e2e/          end-to-end tests (Playwright)
  docs/               experience notes and contract proposals
```

## Run it

```bash
npm install
npm run stub     # terminal 1 - development backend on 127.0.0.1:8000
npm run dev      # terminal 2 - Vite dev server on 127.0.0.1:5173
```

`npm run dev` proxies `/api/*` to the backend, so the browser only ever talks
to one origin.

## Verify it

```bash
npm run lint        # eslint
npm run typecheck   # tsc --noEmit
npm run test        # vitest (unit + integration)
npm run build       # typecheck + production build
npm run test:e2e    # playwright (real browser, real HTTP)
```

`npm run verify` runs lint, typecheck, unit tests and the build in one go.

## What is real and what is not

| Capability | Status | Notes |
|---|---|---|
| Microphone input | **REAL** | Web Speech API (`SpeechRecognition`). Not Alexa+. |
| Spoken responses | **REAL** | Web Speech Synthesis API, with a watchdog for engines that never start. |
| Intent resolution | **Contract only** | The browser sends the v1 request and renders the v1 response. The resolver itself belongs to Agent 1. |
| Movie companion | **REAL** | Real MP4 playback, real subtitle cues from the shipped official track, events driven by `video.currentTime`. |
| Music / games | **Backend driven** | Only what the backend reports is shown. Nothing is faked. |

The `npm run stub` backend is a **development double**. It answers the v1
contract so the client can be built and tested before the real services exist,
and it reports `mode: "stub"` so the interface labels it honestly instead of
presenting it as live.

See `docs/EXPERIENCE.md` for the full capability matrix and the browser
limitations that matter for the demo.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VITE_SIDECKICK_API_BASE` | `''` (same origin) | Absolute API base URL for a deployed backend. |
| `VITE_SIDECKICK_INTERPRET_PATH` | `/api/v1/requests` | Request endpoint. |
| `VITE_SIDECKICK_CAPABILITIES_PATH` | `/api/v1/capabilities` | Capability inventory endpoint. |
| `VITE_SIDECKICK_MEDIA_PATH` | `/api/v1/media/catalog` | Media catalog endpoint. |
| `SIDECKICK_API_TARGET` | `http://127.0.0.1:8000` | Dev proxy target (build/run side). |

Only paths are configurable - the request and response shapes come from
`.sidekick/API_CONTRACTS.md` and are not negotiable client-side.
