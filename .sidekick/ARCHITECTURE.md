# Sidekick Architecture

Module boundaries and design decisions. Owned by Agent 1. Preserve existing conventions; do not duplicate.

## Product mission (non-negotiable)

Sidekick is a voice-first, context-aware action companion. It understands evolving intent, not just a single classified string: "Open YouTube and play a song - no, wait, Spotify" must resolve to the final intended destination before a conflicting action executes. It supports multi-action requests, parameter corrections, clarifying questions, interruption, pause/suspend/resume/switch, session-aware references, pending-action visibility, and safe confirmation for consequential operations. It truthfully reports what happened and what did not.

## Design principles

- Real functionality only. No faked voice input, timer-driven subtitle pop-ups presented as sync, fictional service connections, simulated backend success presented as real, or unverified Alexa+ claims.
- Model interpretation is separate from deterministic safety policy and tool execution. The model cannot override safety policy.
- Session state is isolated by explicit session ID/header/context. No global singleton for user task storage. Two concurrent sessions must not see each other's active tasks or pending actions (tested).
- Action status is driven by actual worker/tool results, never invented frontend timers.
- High-impact or irreversible actions require explicit approval; a confirmation binds to the exact pending action and expires if the plan changes.
- Fallback identity is observable: never silently change models or represent a fallback as the intended model. Expose provider/model used, fallback flag, latency, load errors.
- Keep private chain-of-thought hidden from users; give concise decisions, progress, and actionable clarification questions.
- Handle missing credentials, permissions, network outages, provider timeouts, and unavailable Alexa+ with honest, recoverable states.

## Module boundaries

### Core (Agent 1)

- **Intent resolution**: parses the complete available utterance + context + correction signals into a structured, validated intent. Structured output schema, validation, deterministic post-processing. Never executes on a partial transcript while ASR is still revising unless streaming policy explicitly allows a safe reversible action.
- **Action planning**: splits multi-action requests only when segments are independently resolvable; preserves order and dependencies; never silently drops segments, duplicates actions, or executes partial plans after unresolved risky ambiguity.
- **Session context**: session-scoped storage; active task, suspended tasks, relevant entities; expiry/limits; thread-safe; bounded retention; no cross-session entity leakage.
- **Corrections**: a later correction supersedes the earlier destination before execution where possible. If the old action already began and cannot be cleanly cancelled, stop/compensate safely and explain state instead of pretending it never happened.
- **Safety / deterministic policy**: post-interpretation validation of destination, tool, risk, approval, and arguments. Cannot be bypassed by model output.
- **Tool/action registry contract**: validated capabilities; provider/fallback semantics.
- **Request/response contract**: see `API_CONTRACTS.md`.

### Execution (Agent 2)

- Real coding-agent execution, safe workspace operations, job lifecycle, real tool/service adapters behind the contract.

### Experience (Agent 3)

- Premium UI, real voice input/output, playable movie companion with subtitle timing tied to actual media playback, music/game experiences where technically available, accessibility. Chess is one example, not the whole game strategy.

### QA / Release (Agent 4)

- Automated checks, end-to-end validation, merge gate, hackathon rule evidence, release/deployment verification.

## Session isolation

- In-memory session-scoped storage is appropriate for a local single-process prototype; persistence/restart limits are documented.
- Concurrency: two session IDs tested side by side proving no cross-talk.

## Model/provider

- The previous build used `convaiinnovations/laya` with deterministic policy fallback. Treat as a useful lead, not a guaranteed dependency. Verify availability, license, resource needs, and loading behavior before committing to it.
- Retain the ability to test policy behavior without network/model credentials.
- Lazy loading/caching must not make the first request hang without progress or timeout handling.

## Status vocabulary

`pending`, `awaiting_confirmation`, `running`, `paused/suspended`, `succeeded`, `failed`, `cancelled`, `superseded`.

## Correction policy

- A correction changes an unexecuted plan before execution.
- For an in-flight action, the correction cancels/supersedes it where the adapter supports cancellation; otherwise stop/compensate safely and explain.
- A confirmation must bind to the exact pending action and expire if the plan changes.

## Implementation notes (Phase 1, Agent 1)

These are the decisions the implementation actually makes. They refine the principles above; they do
not replace them.

### The capability catalog is the vocabulary

`sidekick/core/catalog.py` holds the descriptions of every capability (aliases, arguments, risk,
destinations). It is the single source of truth and it is *data*:

- the decision model's answer space is generated from it (a new capability needs no retraining),
- the deterministic fallback matches the aliases in it (adding a capability makes it recognisable
  without touching the brain),
- the safety policy reads the risk and approval rules from it,
- the UI reads it through `GET /v1/tools`.

No keyword list lives inside the engine.

### Who decides what

| Question | Decided by | Why |
|---|---|---|
| Which capability? | the **deterministic matcher decides which capabilities the utterance supports**; the model chooses *between* them | measured with the real model: on an answer space it is not calibrated for it answered "order dinner for me" and "xyzzy plugh" with "read my notes" *and reported success* |
| Which service/destination? | the model, but only among the destinations the utterance mentions | the model answers destinations with 100% accuracy when there is one and invents one with ~0.3 confidence when there is not |
| Is this a correction? | the deterministic discourse markers, plus the model's `is_correction` signal | measured: the model scored 0.03 on a clear correction, the markers are reliable |
| Is this a control verb (cancel, pause, resume)? | the deterministic control grammar only | measured: with control intents in the answer space the model picked a control more often than the right capability |
| Is this a question about the product? | the deterministic capability-question grammar | the answer comes from the catalog; the word "actually" in "what can you actually do" is also a correction marker |
| How many actions? | the deterministic segmentation | splitting must never lose a segment; the model has no reliable multi-action signal |
| Is it safe, does it need approval, are the arguments valid? | the deterministic safety policy | the model can never grant itself permission |

The rule is simple: **the model interprets, the deterministic layers decide.** Every deterministic
override is visible in the response (`decision_model.fallback_used` plus the reason).

#### The anchor

`DecisionEngine._anchor_to_utterance` is the gate the model's answer passes:

- the deterministic matcher computes which capabilities the utterance supports
  (content-word matching against the catalog's aliases);
- if the model's capability is one of them, the model decides;
- if it is not, the model is **overruled** and the deterministic candidate is used;
- if the utterance supports nothing, the answer is an honest "I do not have a capability for that
  yet" - never an arbitrary action.

A destination that exactly one capability owns also identifies that capability, so "no, I meant
Spotify" resolves to the capability that owns Spotify.


### Corrections are resolved before the model sees the text

A correction marker splits the segment into *preceding* (superseded) and *residue* (authoritative).
The model only interprets the residue, so the stale destination can never reach an action. Measured
against the real model: on "Open YouTube, no wait, open Spotify" the model picked YouTube; on the
residue alone it picks Spotify, which is the correct answer.

Two positions of the marker mean different things and are handled differently:

| Marker | Meaning | What it supersedes |
|---|---|---|
| in the middle ("open YouTube, no wait, open Spotify") | the residue replaces what came before it | the earlier segments of this turn **and** the previous turn's pending actions |
| at the end ("echo hello instead") | the instruction replaces the previous *request* | the previous turn's pending actions only - this turn's plan stays intact |

That distinction is what makes "cancel that and echo hello instead" do both things: the cancel
runs, the echo runs, and the stale work from the previous turn is superseded.

### Argument binding

Arguments come from the segment (catalog enum values, durations, counts, quoted or named text, or the
text that follows the tool alias), then from the session (the same tool's previous arguments), then
from a clarification question. The order matters: an explicit value in the utterance always wins over
the remembered one.

### Async actions

An adapter may return `ToolResult(ongoing=True)`. The action then stays `running` and the adapter
reports the final outcome through `ToolContext.complete()`. This is how a real timer behaves: the
action is genuinely in flight and can genuinely be cancelled.

### Session state

`sidekick/core/sessions.py` keeps one `SessionState` per session id, guarded by a lock, with an idle
TTL, a maximum number of sessions (LRU eviction) and per-session limits on actions, tasks and cached
responses. Actions are stored exactly once; tasks reference them by id.
