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
| Movie playback | `REAL_AND_VERIFIED` | The bundled *Letter V* really plays; the E2E suite waits for `readyState >= 1`, asserts a real duration and plays it. |
| Subtitle synchronisation | `REAL_AND_VERIFIED` | Cue lookup is a pure function over `video.currentTime`; the E2E suite plays the film and asserts the caption shown matches the real playback position. |
| Movie Buddy reactions | `REAL_AND_VERIFIED` (caption-based) | Each reaction fires on a real caption line that satisfies a real rule. The trigger is recorded and shown in "Why did Sidekick react?". |
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

- **Commands** (spoken or typed): turn on / turn off / resume Movie Buddy,
  be quiet, what just happened, explain that moment, pause, go back 30
  seconds, and "play me a movie and turn on Movie Buddy".
- **Activation** sets the mode; it never selects a film. When no media is
  available the surface offers the bundled open-licensed film and a file
  picker.
- **Reactions** only happen when a real caption line satisfies a real rule.
  The rules are: the first line of the track, a line that states a plan, a
  line marked as a sound, a step, a step that repeats an earlier one with a
  variation, and the final line. Blank caption lines never trigger anything.
- **The companion is deliberately quiet.** It has a speaking budget of three
  remarks a minute, a twelve-second cooldown, and it never speaks while a
  caption is on screen. `Quiet` stops it immediately for a minute.
- **Answers are grounded.** "What just happened?" quotes the captions from the
  last 45 seconds. "Explain that moment?" quotes the captions around the
  moment. When no caption covers the moment the answer says exactly that, and
  states that there is no picture analysis.
- **"Why did Sidekick react?"** shows the actual trigger: the rule that fired
  and the caption line with its timestamp. It also shows what the companion
  would be holding back for right now (a caption on screen, the budget, the
  cooldown, quiet mode).

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
