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

## Pending decisions

- Model/provider selection for intent resolution (verify `convaiinnovations/laya` plus alternatives)
- AWS target for Phase 5 deployment
- Alexa+ integration path and fallback (verify actual access; document limitation if native access unavailable)
