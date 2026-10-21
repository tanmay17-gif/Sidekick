# Sidekick experience notes - Agent 3

This document records what the browser surface actually does, what it does not
do, and which browser limitations affect the demo. It follows the claim levels
defined in `.sidekick/TEAM_PLAYBOOK.md` §8.

## Capability matrix

| Capability | Claim level | Evidence |
|---|---|---|
| Microphone capture and speech-to-text | `REAL_AND_VERIFIED` in Chromium | `web/src/lib/voice/recognition.ts`; exercised by the browser E2E suite (unsupported-browser path) and by the error-mapping unit tests. |
| Spoken responses (text-to-speech) | `REAL_AND_VERIFIED` in Chromium | `web/src/lib/voice/synthesis.ts`; chunking, cancellation and the "engine never starts" watchdog are unit tested. |
| Request / response contract | `REAL_AND_VERIFIED` | `web/src/lib/api/client.ts` implements `.sidekick/API_CONTRACTS.md` v1. Session id is sent in both the `x-sidekick-session-id` header and the body field. |
| Backend error surfacing | `REAL_AND_VERIFIED` | Transport failure, timeout, HTTP error and contract violation are all distinct, tested states. |
| Decision trace | `REAL_AND_VERIFIED` | Every step renders a field the backend actually sent; where the backend reports no reason, the trace says so. Unit tested plus an end-to-end check that the raw payload is inspectable. |
| Two interfaces, one session | `REAL_AND_VERIFIED` | Interface A and Interface B read the same request list, session id and event stream. Verified end to end in a real browser. |
| Movie playback | `REAL_AND_VERIFIED` | The bundled *Duck and Cover* clip really plays; the E2E suite waits for `readyState >= 1`, asserts a real duration and plays it. |
| Subtitle synchronisation | `REAL_AND_VERIFIED` | Cue lookup is a pure function over `video.currentTime`; the E2E suite plays the film and asserts the caption shown matches the real playback position. |
| Movie Buddy reactions | `REAL_AND_VERIFIED` (caption-driven) | A remark is produced by the engine in `web/src/lib/movie/engine.ts` from a window of real caption cues around the media clock, and the trigger and the grounding are recorded and shown in "Why did Sidekick react?". The unit suite proves the remark changes with the active film. |
| Movie Buddy commentary source | `REAL` when a provider is configured, otherwise `LOCAL_HEURISTIC` | The provider is chosen in `web/src/lib/movie/provider.ts`. The interface always names the source of the last remark (`model`, `local heuristic`, `unavailable`) and never claims a model wrote a remark it did not. |
| Commentary model provider | `NOT_CONFIGURED` in this repository | The core exposes no free-form generation endpoint, and no provider credentials exist. The client is configured through `VITE_SIDECKICK_COMMENTARY_*`; without it the local heuristic is used and says so. |
| Subtitles for an arbitrary video | `REAL_AND_VERIFIED` | "Open a video" plus "Load subtitles" accept any local video with a `.srt` / `.vtt` file. The file is parsed in the browser; nothing is uploaded. |
| Subtitle / media alignment | `REAL_AND_VERIFIED` | `alignmentReport` compares the caption coverage with the media duration and reports `ok`, `no-cues` or `mismatch`, and the mismatch is shown to the viewer. |
| Intent resolution / decision engine | `REAL_AND_VERIFIED` against the real backend | Verified on 2026-10-21 against the merged core (`main` @ `fcd2427`): the client showed `backend LIVE`, the real tool inventory, the streamed progress events and the action the real engine chose. Re-run with `node scripts/verify-real-backend.mjs`. |
| Coding job execution and diff | `REAL_BUT_UNVERIFIED` | The client renders the real diff, the changed-file list and the real test result (Agent 2's issue #6 is closed on this side). The execution service was not reachable from this environment, so the end-to-end path is unproven. |
| Music providers | `NOT_CONFIGURED` | No provider credentials exist. The UI shows the provider list with `unconfigured` state and explains what is needed. |
| Chess | `REAL_BUT_UNVERIFIED` | The board is rendered from the FEN the backend reports; move legality is never decided in the browser. |
| Local games (tic-tac-toe, 2048) | `REAL_AND_VERIFIED` | The rules, the minimax opponent and the board state are real and run in the browser. Labelled `local`. |
| Alexa+ | `NOT_IMPLEMENTED` | No Alexa skill is implemented. The browser uses the Web Speech API, which is **not** an Alexa+ integration and must not be presented as one. |
| A real coding model provider | `NOT_CONFIGURED` | No `SIDEKICK_LLM_API_KEY` and no local coding CLI exists on any agent machine (Agent 2 reports the same). The capability report says `NOT_CONFIGURED`, so the interface shows the truthful status rather than a broken button. |

### Verified against the merged core

On 2026-10-21 the client was run against the **merged** core (`main` @ `fcd2427`),
served through the Vite proxy:

- the capability strip read `backend LIVE` and listed the five real tools
  (`note.write`, `note.read`, `timer.set`, `timer.list`, `media.open`);
- a typed request was resolved by the real engine, which chose `note.write`
  and **actually wrote the note to disk** - the result payload showed the real
  path, byte count and title;
- the **event stream** worked against the real backend: "interpreted with
  sidekick/rule-engine-v1", "1 action(s) planned", "note.write started",
  "note.write succeeded", each with a real timestamp;
- the response metadata showed the real provider and model, and the client
  surfaces `fallback_used: true` as `rule-engine-v1 (fallback)` rather than
  hiding the fallback.

`web/scripts/verify-real-backend.mjs` automates those checks. It is kept out of
`npm run test:e2e` because it needs the Python backend running:

```bash
# terminal 1 - the real backend
python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8040
# terminal 2 - the built client, pointed at it
SIDECKICK_API_TARGET=http://127.0.0.1:8040 npx vite preview --port 4178
# terminal 3
node scripts/verify-real-backend.mjs http://127.0.0.1:4178 http://127.0.0.1:8040
```

## The decision trace

The trace is the difference between "the AI did something" and "here is what
Sidekick understood, chose and did". It shows:

1. **Heard** - the utterance and whether it came from the microphone or the
   keyboard.
2. **Understood** - the normalized intent, the confidence, whether the backend
   marked it ambiguous, and how many entities it extracted.
3. **Decided** - the provider, the model, the source, whether a fallback ran,
   and the risk level.
4. **Planned** - every action with its tool, description, arguments and
   approval state.
5. **Asked** - the clarification, when the backend asked one. The trace notes
   that the backend reported the question but not the internal reason for it.
6. **Acted** - the events, with their sequence numbers, types and timestamps.
7. **Result** - the outcome, the error code, the changed files, the test result
   and the diff.

Nothing in the trace is a rationale the browser invented. Where the contract
does not expose a reason, the trace shows the observed facts and says the
reason is unavailable.

The raw response payload is one click away (`Raw payload`) for the demo, and
it is hidden by default so the main surface does not look like a debugging
tool.

## Action state, ownership and the two interfaces

### The bugs that were fixed, and their actual causes

| Symptom | Root cause | Fix |
|---|---|---|
| `No route for POST /api/v1/actions/{id}/cancel` | The **development stub** only matched `GET /actions/{id}` and `GET /actions/{id}/events`; the approve and cancel routes fell through to its catch-all 404. The real core implements both routes. | The stub now matches all four action routes, and the client's error message is the backend's message rather than a raw status. |
| Cancelling returned 422 | The contract expects **`session_id` in the body** of the approve and cancel calls - the session header is not consulted by those endpoints - and the client was sending `{}`. | The client sends `{ session_id, approved, plan_hash }` for approve and `{ session_id }` for cancel, and parses the `{ action }` envelope those endpoints return. |
| An old `game.chess` action stayed `PENDING` while a music request was on screen | Two causes: the stub never moved an action past `pending`, and the client showed the whole `action_plan` of a response without separating the actions the current request owns from the ones the backend carried over from an earlier turn. | The stub runs the real lifecycle (pending -> running -> succeeded / failed / cancelled, with cancellation honoured while in flight). The client records which request produced each action id and marks the carried-over ones `inherited`; the conversational surface only ever shows the current request's actions, and the developer view lists the inherited ones separately. |
| An approval looked like it did nothing | The approval response is `{ action }`, not a `SidekickResponse`, so the client was writing a malformed record back into the state. | The client parses the action envelope, then re-reads the action so the shown state is the backend's, never an optimistic guess. |
| A new session still showed the previous session's work | The session id was reset but the request list, the action-ownership map and the phase were not. | `resetSession` now clears the requests, the ownership map, the live events, the action errors and the phase, and the speech output is cancelled with it. |

### The states the interface shows

The contract's action states are `pending`, `awaiting_confirmation`, `running`,
`paused`, `succeeded`, `failed`, `cancelled` and `superseded`. The interface
adds exactly one derived state, **`timed_out`**, which is a failure whose
error says it timed out - the contract has no separate state for it, so it is
derived rather than invented.

An action is only ever shown as succeeded when the backend reported
`state: "succeeded"`. A request that was merely submitted, acknowledged or
streamed is never presented as a success.

### What each interface shows

**Interface A - Ask Sidekick / Movie Buddy.** The conversational surface. It
shows what you said, what Sidekick answered, and what is happening - in plain
language. It never shows a tool name, a request id, a session uuid, a
confidence number, a model name or a raw payload. The raw detail lives in the
developer view.

**Interface B - Developer (Sidekick Live Control Room).** The architecture
diagram, the request inspector with the real ids and provenance, the task
timeline fed by the real event stream, the capability health table, and the
raw payload. The approve / refuse / cancel controls are here as well, and
they call the real endpoints.

Both interfaces read **one** `useSidekick` instance: the same request list, the
same session id and the same events.

## Voice input - real behaviour and limits

`web/src/lib/voice/recognition.ts` wraps `SpeechRecognition` /
`webkitSpeechRecognition`.

- **Support detection.** If the API is missing the microphone button is
  disabled, the input method switches to `text only`, and the text field stays
  usable. The browser never silently pretends to listen.
- **Permission states.** `navigator.permissions.query({ name: 'microphone' })` is
  used for a pre-flight check where the browser exposes it (Chromium). Firefox
  and Safari do not expose the descriptor, so the client reports `null` and
  relies on the engine's own error events.
- **Distinct failure states.** `not-allowed` (permission denied), `service-not-allowed`
  (engine blocked, typical of private windows), `audio-capture` (no microphone),
  `no-speech` (nothing heard), `network` (speech service unreachable),
  `aborted` (cancelled) and an inactivity timeout each produce their own
  message. None of them is reported as a successful capture.
- **Interim vs final.** Interim transcripts are shown in a muted italic style.
  Only a final transcript is sent to the backend, with `utterance_finalized: true`.
- **Interruption.** While the assistant is speaking the microphone button becomes
  an interrupt control: it cancels the speech synthesis queue and aborts the
  in-flight request.
- **Voice errors never disable the text field.** The error is shown next to the
  composer and the composer keeps working.

### Known browser limits

- Chromium's speech recognition is a **cloud service**. Audio leaves the
  device, the feature needs network access, and it is not available offline.
  The `network` error state exists for this reason.
- Chromium may return `service-not-allowed` in private windows and when
  third-party scripts are blocked.
- Safari and Firefox expose `SpeechRecognition` inconsistently; the text
  fallback is the guaranteed path there.
- Recognition quality depends on the browser's engine and the microphone. The
  demo should still be able to fall back to typing without any degradation of
  the rest of the product.

## Speech output - real behaviour and limits

`web/src/lib/voice/synthesis.ts` wraps `speechSynthesis`.

- Text is split into sentence-sized chunks because Chromium stops long
  utterances after roughly 15 seconds.
- If the engine never starts (no installed voice, blocked by the OS) a
  watchdog fires after 1.8 seconds, the UI leaves the speaking state and the
  reason is shown in the composer. The interface never stays stuck on
  "speaking".
- Pressing the microphone while speaking cancels the queue immediately.

## Movie Buddy

Movie Buddy is a **companion mode**, not a film. Switching it on is
independent of which film is playing: "Turn on Movie Buddy" works with any
source, and the film can be chosen before or after.

### What it was before this milestone

The commentary was **hardcoded**. `web/src/lib/movie/buddy.ts` exported
`reactToCue`, which returned one of six fixed strings - `'Hi. Watching with
you.'`, `'Right - here is the plan.'`, `'Listen to that.'`, `'Same idea again,
slightly different.'`, `'Step by step.'`, `'That is the end of it.'` - chosen by
a rule list. Two of those rules were English-verb specific: `IMPERATIVE`
matched a literal list of English verbs (`inflate|twist|lock|take|...`) and a
second rule matched `/\bwe are going to\b|\bwe'll\b|\blet's\b/i`. Both were
tuned to the narration of *Duck and Cover*. There was no model call anywhere in
the client, the context was used only for a word-overlap check, and the words
Sidekick spoke did not depend on what the captions actually said.

### How it works now

```
video.currentTime
   -> the caption line that has just been said      (context.ts)
   -> a bounded window of dialogue                   (context.ts)
   -> a usefulness decision                          (engine.ts)
   -> the commentary provider                        (provider.ts)
   -> a remark that is grounded in the cues it saw  (provider.ts)
   -> the speaking gate                              (engine.ts)
   -> speech
```

- **The cue.** The companion talks about the last caption line that has
  *started* - the line the viewer has just heard. It never speaks while a line
  is on screen; it speaks in the gap after one. A line it had to stay quiet
  for is not marked as considered, so it can still be remarked on later.
- **The window.** `buildCueWindow` returns the previous 3 cues, the current
  cue, the next 2 cues and a bounded recent window (8 cues). The provider is
  given that window and **never** the whole subtitle file.
- **The decision.** The engine suppresses the remark when a caption is on
  screen, when the line is doing the work (long, emphatic, or a question with
  real content in it), when the same moment was already remarked on (even
  after a seek back), when the speaking budget for the minute is spent, when
  the cooldown has not expired, or when the viewer asked for quiet.
- **The provider.** `web/src/lib/movie/provider.ts` has three:
  - `createModelProvider` - calls a configured OpenAI-compatible endpoint. The
    request is cancellable, has a timeout, and is rate limited independently of
    the speaking budget (at most one call every 4 seconds).
  - `createLocalProvider` - a deterministic fallback that only reports what it
    can observe in the captions (a repeated phrase, a new term, a sound, a
    question). It is labelled **local heuristic**, never "model".
  - `createUnavailableProvider` - used when there is nothing to read, and it
    explains why.
- **The grounding check.** A model answer must be JSON with a `say` string and
  a `grounded_in` list of cue indexes. An answer that is not JSON, is too long
  to speak, or names a cue the provider was never shown is **rejected** and
  nothing is spoken. This is the check that stops the companion from
  fabricating.
- **The source is always visible.** The interface shows `model`,
  `local heuristic` or `unavailable` next to the remarks, and the "why" panel
  repeats it for the last remark.

### The provider configuration

There is no free-form generation endpoint in the core (it exposes
`/api/v1/requests`, `/api/v1/decide` and the action routes - a decision, not
free text), so the commentary provider is configured on the client side:

| Variable | Default | Purpose |
|---|---|---|
| `VITE_SIDECKICK_COMMENTARY_ENDPOINT` | unset | An OpenAI-compatible chat completions URL. **Unset means no model provider.** |
| `VITE_SIDECKICK_COMMENTARY_MODEL` | `sidekick-commentary` | The model name sent with the request. |
| `VITE_SIDECKICK_COMMENTARY_API_KEY` | unset | Optional bearer token. |
| `VITE_SIDECKICK_COMMENTARY_TIMEOUT_MS` | `8000` | Abort a provider call that has not answered in time. |

Without `VITE_SIDECKICK_COMMENTARY_ENDPOINT` the client uses the local
heuristic and says so in the interface. It never claims a model wrote a remark
it did not write.

### The rest of the behaviour

- **Commands** (spoken or typed): turn on / turn off / resume Movie Buddy,
  be quiet, what just happened, explain that moment, pause, go back 30
  seconds, and "play me a movie and turn on Movie Buddy".
- **Activation** sets the mode; it never selects a film. When no media is
  available the surface offers the bundled open-licensed film and a file
  picker.
- **Any video.** "Open a video" plays a file from this device and "Load
  subtitles" attaches a `.srt` or `.vtt` file to it. The file is parsed in the
  browser and never uploaded. A video with no caption track gets a clear
  notice that the companion has nothing to read, and the "load subtitles"
  affordance.
- **Alignment.** If the captions stop long before the film ends, the interface
  warns that the subtitles may not match this copy of the film.
- **Re-evaluation.** A seek, a pause, a resume and a subtitle-track change all
  re-evaluate the moment instead of reasoning about the one that has moved on.
- **Answers are grounded.** "What just happened?" quotes the captions from the
  last 45 seconds. "Explain that moment?" quotes the captions around the
  moment. When no caption covers the moment the answer says exactly that, and
  states that there is no picture analysis.
- **"Why did Sidekick react?"** shows the actual trigger: the observable
  property of the caption line, the line with its timestamp, and the source of
  the words. It also shows what the companion would be holding back for right
  now.

### What it is not

- It does **not** analyse the picture. It only reads captions.
- It does **not** describe off-screen action, character intention or plot.
- It does **not** work on a streaming service in another tab, and it never
  pretends to.
- It does **not** speak over dialogue.

See `MOVIE_SOURCES.md` for the film, the rights evidence and the exact
limits on what the companion can observe.

## Integration notes for the other agents

- The client never invents a result. A transport failure, a timeout, a
  non-contract body or a missing provider all produce their own visible state.
- Capability badges come from the backend's `/capabilities` response. If the
  backend reports a capability as `simulated`, the interface says `simulated`.
  The execution vocabulary (`REAL | SIMULATED | NOT_CONFIGURED | NOT_IMPLEMENTED
  | UNAVAILABLE`) is rendered verbatim next to the browser vocabulary.
- The browser sends the session id in both the header and the body, and honours
  the documented precedence (header wins).
- Agent 2's issue #6 is closed on this side: an action result now shows the
  diff, the changed-file list **and** the test result together, and a
  `partial` outcome is never rendered as a success.
- **Proposal for Agent 1 (not implemented here, because the core is Agent 1's
  file).** The core has no free-form generation endpoint, so the commentary
  provider had to be configured in the browser client. A
  `POST /api/v1/commentary` route on the core - taking a bounded cue window
  and returning `{ say, grounded_in }` - would let the companion use the same
  model the rest of the product uses and keep the API key on the server. The
  client already speaks OpenAI-compatible chat completions, so pointing it at
  such a route is a configuration change, not a code change. **No core file was
  touched by this milestone.**
- The core's media catalog still carries `companion_rules`
  (`web/src/lib/media/companion.ts`); the rules are honoured by the contract
  level event builder, and the *adaptive* commentary path in
  `web/src/lib/movie/` is independent of them.
