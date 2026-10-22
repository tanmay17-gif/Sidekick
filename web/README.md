# Sidekick web client

The browser surface of Sidekick. Two interfaces, one session:

- **Interface A - Ask Sidekick / Movie Buddy.** The conversational surface you
  talk to. A large companion that reflects what Sidekick is actually doing, a
  readable transcript, and a movie companion that reads the captions of the
  film you are watching and remarks on them in the gaps between the lines.
- **Interface B - Control room.** The developer view of the *same* session: the
  live architecture diagram, the decision metadata for every request, the task
  timeline fed by the real event stream, and the true status of every
  capability.

This package is owned by **Agent 3 (Product Experience)**.

```
web/
  src/
    lib/api/          contract v1 client, types, error normalisation
    lib/voice/        Web Speech recognition + synthesis wrappers
    lib/media/        subtitle parsing, cue lookup, the movie player state
    lib/movie/        the Movie Buddy engine, providers and control commands
    lib/games/        FEN rendering, local game rules
    state/            the shared session state machine
    components/       the interface
  public/media/       the openly licensed films and their captions
  dev/stub-server.mjs SIMULATED_TEST_ONLY development backend
  tests/unit/         unit + integration tests (Vitest)
  tests/e2e/          end-to-end tests (Playwright)
  docs/               experience notes, rights evidence, demo script
```

## The two interfaces

**Interface A - Ask Sidekick / Movie Buddy.** The voice-first surface a person
talks to: a large animated companion that reflects what Sidekick is actually
doing, the exchange in plain language, one prominent microphone and a text
alternative. No tool names, request ids, session uuids, confidence numbers,
model names or raw payloads appear here.

**Interface B - Developer (Sidekick Live Control Room).** The live
architecture diagram, the request inspector, the task timeline fed by the real
event stream, the capability health table, the approve / cancel controls and
the raw payload.

Both read the same session, so a request made in one is the same request, the
same action and the same ids in the other.

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

Thirteen checks: the backend mode is reported verbatim, every published
capability is shown, a request is answered by the real engine with the tool it
chose, **both interfaces show the same request and the same ids**, the real
model and confidence are displayed, the architecture diagram does not draw
anything as live that the backend did not report, the bundled film really
loads, and nothing threw.

```bash
node scripts/verify-real-flow.mjs http://127.0.0.1:4178 http://127.0.0.1:8040
```

The exact sequence from the brief, against a real backend: start an unrelated
action, submit *"Open YouTube and play a song - no wait, Spotify."*, confirm
the music request does not inherit the earlier action, cancel a running action
and compare the backend's answer with the interface, start a new session and
confirm nothing is carried over, and capture the normal experience.

## What is real and what is not

| Capability | Status | Notes |
|---|---|---|
| Microphone input | **REAL** | Web Speech API (`SpeechRecognition`). Not Alexa+. |
| Spoken responses | **REAL** | Web Speech Synthesis API, with a watchdog for engines that never start. |
| Intent resolution | **REAL** (against the merged core) | Verified end to end: the request is answered by the real engine and a real note is written to disk. |
| Interface A / Interface B | **REAL, one session** | Both read the same request list, session id and event stream. |
| Architecture diagram | **REAL** | Every node's state comes from the backend's own capability report. |
| Movie playback | **REAL** | A bundled public-domain film, played for real, with its own captions. |
| Movie Buddy | **REAL, caption-driven** | Remarks are produced from a bounded window of real caption cues around the media clock. The trigger and the grounding are shown. There is **no visual analysis** and the interface says so. |
| Movie Buddy commentary | **REAL, model-backed when configured** | The provider is chosen at runtime. The interface always names the source of the last remark: `model`, `local heuristic` or `unavailable`. |
| Commentary model provider | **NOT CONFIGURED** | The core has no free-form generation endpoint and no credentials exist here. Set `VITE_SIDECKICK_COMMENTARY_ENDPOINT` to use one; without it the local heuristic is used and labelled as such. |
| Subtitles for your own video | **REAL** | "Open a video" + "Load subtitles" (`.srt` / `.vtt`). Parsed in the browser; never uploaded. |
| Coding job diff | **REAL, unverified end to end** | The client renders the real diff, changed files and test result. The execution service was not reachable from this environment. |
| Music / game providers | **NOT CONFIGURED** | No credentials. The interface explains what is needed instead of faking a player. |
| Alexa+ | **NOT IMPLEMENTED** | The Web Speech API is not Alexa+ and is never presented as one. |

The `npm run stub` backend is a **development double**. It answers the v1
contract so the client can be built and tested before the real services exist,
and it reports `mode: "stub"` so the interface labels it honestly instead of
presenting it as live.

## The film

The default film is **Duck and Cover** (1951) - a U.S. Federal Civil Defense
Administration production, therefore **public domain**. A 2:30 clip is bundled
with the app, with a caption track built from the archive's own transcription
of the narration.

Two more films are available: *Letter V* (CC0 1.0, bundled) and *Tears of
Steel* (CC BY 3.0, streamed). The exact copies, the rights evidence and the
limits are in `docs/MOVIE_SOURCES.md`.

You are not limited to those films: **Open a video** plays a file from this
device and **Load subtitles** attaches a `.srt` or `.vtt` file to it. The
companion then reads those captions. If the captions stop long before the film
ends, the interface warns that they may not match that copy.

## How Movie Buddy decides to speak

```
video.currentTime
   -> the caption line that has just been said
   -> a bounded window (3 before, the current one, 2 after, 8 recent)
   -> a usefulness decision (never over dialogue, never twice, budget, cooldown)
   -> the commentary provider
   -> a remark grounded in the cues it was shown
   -> speech
```

The provider is one of:

- **model** - a configured OpenAI-compatible endpoint
  (`VITE_SIDECKICK_COMMENTARY_ENDPOINT`). The call is cancellable, has a
  timeout, is rate limited, and is given a *window* of cues - never the whole
  subtitle file. An answer that names a cue the provider was never shown is
  rejected.
- **local heuristic** - the deterministic fallback, used when no endpoint is
  configured. It only reports what it can observe in the captions. It is
  labelled `local heuristic`, never "model".
- **unavailable** - when there is nothing to read; the interface says why and
  asks for a subtitle track.

The source of the last remark is always visible in the Movie Buddy panel.

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
| `VITE_SIDECKICK_COMMENTARY_ENDPOINT` | unset | OpenAI-compatible chat completions URL for Movie Buddy commentary. Unset = no model provider. |
| `VITE_SIDECKICK_COMMENTARY_MODEL` | `sidekick-commentary` | Model name sent with a commentary request. |
| `VITE_SIDECKICK_COMMENTARY_API_KEY` | unset | Optional bearer token for the commentary endpoint. |
| `VITE_SIDECKICK_COMMENTARY_TIMEOUT_MS` | `8000` | Abort a commentary call that has not answered in time. |
| `SIDECKICK_API_TARGET` | `http://127.0.0.1:8000` | Dev proxy target (build/run side). |

Only paths are configurable - the request and response shapes come from
`.sidekick/API_CONTRACTS.md` and are not negotiable client-side.
