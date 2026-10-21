# Sidekick web client

The browser surface of Sidekick: voice in, decision engine out, real outcomes on
screen, and a movie companion that reads the captions of the film you are
actually watching. This package is owned by **Agent 3 (Product Experience)**.

```
web/
  src/
    lib/api/          contract v1 client, types, error normalisation
    lib/voice/        Web Speech recognition + synthesis wrappers
    lib/media/        subtitle parsing, cue lookup, the movie player state
    lib/movie/        the Movie Buddy brain and its control commands
    lib/games/        FEN rendering, local game rules
    state/            the conversation state machine
    components/       the interface
  public/media/       the openly licensed film and its captions
  dev/stub-server.mjs SIMULATED_TEST_ONLY development backend
  tests/unit/         unit + integration tests (Vitest)
  tests/e2e/          end-to-end tests (Playwright)
  docs/               experience notes, rights evidence, demo script
```

## Run it

```bash
npm install
npm run stub     # terminal 1 - development backend on 127.0.0.1:8000
npm run dev      # terminal 2 - Vite dev server on 127.0.0.1:5173
```

`npm run dev` proxies `/api/*` to the backend, so the browser only ever talks
to one origin.

### Against the real backend

```bash
# terminal 1 - the real core
python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8040
# terminal 2 - the built client, pointed at it
SIDECKICK_API_TARGET=http://127.0.0.1:8040 npm run build && npx vite preview --port 4178
```

## Verify it

```bash
npm run lint        # eslint
npm run typecheck   # tsc --noEmit
npm run test        # vitest (unit + integration)
npm run build       # typecheck + production build
npm run test:e2e    # playwright (real browser, real HTTP, real media playback)
```

`npm run verify` runs lint, typecheck, unit tests and the build in one go.

### Against the real backend

```bash
node scripts/verify-real-backend.mjs http://127.0.0.1:4178 http://127.0.0.1:8040
```

The script asserts that the capability strip reports the backend's own mode,
that every published capability is shown, that a request is answered by the
real engine with the tool it chose, and that nothing is faked in the client.

## What is real and what is not

| Capability | Status | Notes |
|---|---|---|
| Microphone input | **REAL** | Web Speech API (`SpeechRecognition`). Not Alexa+. |
| Spoken responses | **REAL** | Web Speech Synthesis API, with a watchdog for engines that never start. |
| Intent resolution | **REAL** (against the merged core) | Verified end to end; the request is answered by the real engine and the real note is written to disk. |
| Decision trace | **REAL** | Every field comes from the backend response. |
| Movie playback | **REAL** | A bundled public-domain film, played for real, with its own captions. |
| Movie Buddy | **REAL, caption-based** | Reactions fire on real caption lines. There is **no visual analysis** and the interface says so. |
| Coding job diff | **REAL, unverified end to end** | The client renders the real diff, changed files and test result. The execution service was not reachable from this environment. |
| Music / game providers | **NOT CONFIGURED** | No credentials. The interface explains what is needed instead of faking a player. |
| Alexa+ | **NOT IMPLEMENTED** | The Web Speech API is not Alexa+ and is never presented as one. |

The `npm run stub` backend is a **development double**. It answers the v1
contract so the client can be built and tested before the real services exist,
and it reports `mode: "stub"` so the interface labels it honestly instead of
presenting it as live.

See `docs/EXPERIENCE.md` for the full capability matrix and the browser
limitations that matter for the demo.

## The movie

The companion plays **Letter V** - a public-domain (CC0 1.0) short that is
bundled with the app, with its own hand-authored English caption track. A
second film, *Tears of Steel* (CC BY 3.0), is streamed from the Internet
Archive. The exact copies, the rights evidence and the limits are in
`docs/MOVIE_SOURCES.md`.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VITE_SIDECKICK_API_BASE` | `''` (same origin) | Absolute API base URL for a deployed backend. |
| `VITE_SIDECKICK_INTERPRET_PATH` | `/api/v1/requests` | Request endpoint. |
| `VITE_SIDECKICK_CAPABILITIES_PATH` | `/api/v1/capabilities` | Capability inventory endpoint. |
| `VITE_SIDECKICK_MEDIA_PATH` | `/api/v1/media/catalog` | Media catalog endpoint. |
| `VITE_SIDECKICK_ACTION_EVENTS_PATH` | `/api/v1/actions/:id/events` | Live action event stream. |
| `VITE_SIDECKICK_APPROVE_PATH` | `/api/v1/actions/:id/approve` | Approval endpoint. |
| `VITE_SIDECKICK_CANCEL_PATH` | `/api/v1/actions/:id/cancel` | Cancellation endpoint. |
| `SIDECKICK_API_TARGET` | `http://127.0.0.1:8000` | Dev proxy target (build/run side). |

Only paths are configurable - the request and response shapes come from
`.sidekick/API_CONTRACTS.md` and are not negotiable client-side.
