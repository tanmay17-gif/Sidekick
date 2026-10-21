# Sidekick Decision Log

Important decisions, alternatives, and reasons. Owned by Agent 1.

## Decisions

| ID | Date | Decision | Alternatives considered | Reason |
|---|---|---|---|---|
| D1 | 2026-10-21 | Four fixed agent roles; Agent 1 owns contracts/playbook/task board | Unfixed roles; shared editing of coordination files | Prevents four agents creating conflicting project structures; single shared source of truth |
| D2 | 2026-10-21 | Default branch `main`; PR-only updates; required CI; no self-approval | Direct pushes to `main` | Protects shared source of truth across four PCs |
| D3 | 2026-10-21 | `.sidekick/` files owned by Agent 1; Agent 4 owns integration evidence files | All agents editing the same coordination files | Prevents conflicting coordination documents |
| D4 | 2026-10-21 | `convaiinnovations/laya` treated as a lead, not a guaranteed dependency | Committing to laya upfront | Availability, license, resource needs, and loading behavior not yet verified |
| D5 | 2026-10-21 | Real functionality only; no faked voice/subtitles/service/Alexa+ claims; test doubles only in tests/dev mode | Mock-heavy build | Product truthfulness requirement; verified claim levels |
| D6 | 2026-10-21 | Session state isolated by explicit session ID; thread-safe/session-scoped storage; no global singleton | Global singleton | Cross-session leakage risk; two-session isolation must be proven |
| D7 | 2026-10-21 | Core brain implemented in Python (FastAPI + pydantic v2); Node is not installed on this PC | TypeScript/Node backend | The only runtime available here is Python 3.13; the decision model (`laya`) is a Python package anyway. The HTTP contract is language neutral for Agent 2/3 |
| D8 | 2026-10-21 | The real decision model is `convaiinnovations/laya` (Apache-2.0, self-hosted), loaded lazily with a hard timeout; the deterministic catalog matcher is the fallback and is always reported | Bedrock / hosted LLM | Verified available on Hugging Face, no API key, non-generative (no hallucinated output), typed questions map 1:1 onto the contract. Model choice can be revisited in Phase 5 |
| D9 | 2026-10-21 | Control verbs (cancel/pause/resume/status/confirm/reject) are resolved by a deterministic grammar and are *not* offered to the model | Letting the model choose control intents | Measured with the real model: with control intents in the answer space it chose a control more often than the right capability (42% tool accuracy). Removing them raised the capability accuracy and made control turns instant |
| D10 | 2026-10-21 | Corrections are split into preceding/residue by discourse markers *before* the model is called; the model only sees the residue | Letting the model resolve the correction | Measured with the real model: it chose the stale destination ("YouTube" for "no wait, open Spotify") and scored 0.03 on `is_correction`. The markers are reliable and general |
| D11 | 2026-10-21 | The model's destination answer is only used above a confidence floor of 0.7; the catalog matcher fills it otherwise | Trusting the model's argmax | The model answers a destination with 100% accuracy when it is sure, but invents one with ~0.3 confidence when the utterance has no destination |
| D12 | 2026-10-21 | `decision_model.fallback_used` is true whenever the interpretation was *not* produced by the configured model (unavailable, timeout, invalid output, low confidence, or a deterministic control) | Reporting only model failures | Otherwise a response could imply the model did the work when it did not |
| D13 | 2026-10-21 | A running action that the adapter cannot stop becomes `paused` with `error.code = cancellation_unsupported`, never `cancelled` | Reporting it as cancelled | The work may still be running; reporting success would be a lie |
| D14 | 2026-10-21 | A plain "and" is only a segment separator when both sides resolve to *different* capabilities | Splitting on every "and" | "echo hello and goodbye" is one request; splitting it would drop the second half |


## Pending decisions

- Model/provider selection for intent resolution (verify `convaiinnovations/laya` plus alternatives)
- AWS target for Phase 5 deployment
- Alexa+ integration path and fallback (verify actual access; document limitation if native access unavailable)
