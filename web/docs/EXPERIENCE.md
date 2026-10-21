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
| Movie playback | `REAL_AND_VERIFIED` | Real MP4 (`tears_of_steel_720p.mp4`) with native controls; the E2E suite covers the load-failure recovery path. |
| Subtitle synchronisation | `REAL_AND_VERIFIED` | Cue lookup is a pure function over `video.currentTime`; verified by unit tests against the shipped official track and by an integration test that moves the media clock. |
| Companion events | `REAL_AND_VERIFIED` (subtitle-based) | Each event timestamp is the real start time of a real cue. No vision pipeline exists, and the UI says so. |
| Intent resolution / decision engine | `REAL_BUT_UNVERIFIED` | The browser sends the contract and renders the contract. The resolver is Agent 1's; the E2E suite runs against the labelled development stub. |
| Coding job execution and diff | `REAL_BUT_UNVERIFIED` | The client renders the real diff from the response payload (including unified-diff line colouring). The job itself is Agent 2's. |
| Music providers | `NOT_CONFIGURED` | No provider credentials exist. The UI shows the provider list with `unconfigured` state and explains what is needed. |
| Chess | `REAL_BUT_UNVERIFIED` | The board is rendered from the FEN the backend reports; move legality is never decided in the browser. |
| Tic-Tac-Toe (local) | `REAL_AND_VERIFIED` | The opponent is a real minimax search over the rules in `web/src/lib/games/tictactoe.ts`. It is labelled `local` so it is never confused with a backend-backed game. |
| 2048 (local) | `REAL_AND_VERIFIED` | The real merge rules in `web/src/lib/games/game2048.ts`. A tile merges once per move, exactly as in 2048. |
| Alexa+ | `NOT_IMPLEMENTED` | No Alexa skill is implemented. The browser uses the Web Speech API, which is **not** an Alexa+ integration and must not be presented as one. |

### Games are not just chess

The games surface has two clearly separated groups:

- **Backend games** - whatever the backend reports through
  `capabilities.games`, with the state it reported. The browser only renders
  them and never decides a move.
- **Local activities** - games that ship with the client and need no service at
  all. Their rules, opponent and state are real and run in the browser, and
  they are marked `local` so nobody mistakes them for a service response.

`web/src/lib/games/registry.ts` is the single place to add another local
activity.

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

## Movie companion - what "real" means here

- **Media.** *Tears of Steel* (2012), Blender Foundation / MPEG, **CC BY 3.0**.
  The stream is the Internet Archive's `tears_of_steel_720p.mp4` derivative
  (faststart H.264/AAC, HTTP range support, so seeking works).
- **Subtitles.** The official English subtitle file `TOS-en.srt` from
  `download.blender.org` is committed at
  `web/public/media/tears-of-steel/TOS-en.srt` and parsed in the browser.
  The 76 cue timings are the timings of the shipped file - nothing is invented.
  The same cues are re-serialised to WebVTT and attached to the `<video>`
  element as a real `<track kind="subtitles">`, so the native player shows
  captions too.
- **Events.** A companion event fires when playback reaches the exact start
  timestamp of a cue whose text matches a rule. The event shows the timestamp,
  the line that triggered it, and why it appeared. There is **no visual
  analysis** - the interface labels the understanding as subtitle-based.
- **Modes.** `Quiet` (no cards, no speech), `Brief` (speaks a short line) and
  `Cards` (raises a card). In `Brief` mode the companion only speaks while no
  cue is on screen, so it never talks over dialogue.
- **Recovery.** If the video or the subtitle track cannot be loaded, the
  surface says so and the rest of the interface keeps working. A subtitle
  failure disables companion events rather than faking understanding.

### Media licensing

The subtitle file is redistributed under CC BY 3.0 with attribution shown in
the UI ("Tears of Steel - Blender Foundation / MPEG (CC BY 3.0)"). The video is
streamed from the Internet Archive rather than vendored into the repository.
No copyrighted material is scraped or redistributed by this client.

## Why the movie companion is not a fake subtitle demo

The previous shape of this feature - a repeating timer that pops up a caption
every few seconds - is exactly what this implementation replaces. Here the
timeline is `video.currentTime`; the cue index is a binary search over the
parsed cue list; seeking recomputes immediately; pausing stops the clock. A
test asserts that every companion event timestamp equals the start time of a
real cue.

## Integration notes for the other agents

- The client never invents a result. A transport failure, a timeout, a
  non-contract body or a missing provider all produce their own visible state.
- Capability badges come from the backend's `/capabilities` response. If the
  backend reports a capability as `simulated`, the interface says `simulated`.
- The browser sends the session id in both the header and the body, and honours
  the documented precedence (header wins).
