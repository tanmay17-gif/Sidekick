# Sidekick Task Board

Phases, dependencies, assigned owner, acceptance criteria, next task. Owned by Agent 1. Status changes only through reviewed PRs or the agreed GitHub issue workflow.

## Current phase

Phase 0 — Recover and coordinate.

## Task states

`BACKLOG` → `READY` → `IN_PROGRESS` → `BLOCKED` → `IN_REVIEW` → `MERGED` → `VERIFIED`

A task is not `MERGED` until the real merge commit exists on the remote base. A task is not `VERIFIED` until its acceptance evidence passes on the integrated code.

## Tasks

| ID | Phase | Task | Owner | Status | Depends on | Acceptance criteria |
|---|---|---|---|---|---|---|
| A1-BOOT | 0 | Repository audit + team protocol / bootstrap PR | Agent 1 | IN_PROGRESS | — | `.sidekick/` coordination files created; PR opened against default branch; merge commit present on remote |
| A1-CONTRACT | 1 | Document + implement minimal request/action contract + first vertical slice | Agent 1 | BACKLOG | A1-BOOT | Contract schemas v1; one real E2E slice (backend call, UI result, automated test); merged |
| A2-AUDIT | 0 | Read-only execution/integration prerequisites inventory | Agent 2 | READY | — | Inventory of runtime/tool/adapter prerequisites |
| A3-AUDIT | 0 | Read-only UI/voice/media prerequisites inventory | Agent 3 | READY | — | Inventory of voice/UI/media prerequisites |
| A4-RULES | 0 | Verify current official hackathon rules; start test/CI plan | Agent 4 | READY | — | Source URLs, date checked, requirement text saved in repo |
| A1-BRAIN | 2 | Intent / session / correction / orchestration behind contracts | Agent 1 | BACKLOG | A1-CONTRACT | Correction (pre-exec + in-flight), multi-action, session isolation (2+ sessions concurrent), safety policy, model/fallback observability tests |
| A2-EXEC | 2 | Real execution + integration adapters | Agent 2 | BACKLOG | A1-CONTRACT | — |
| A3-UI | 2 | Design system + real voice/UI foundations | Agent 3 | BACKLOG | A1-CONTRACT | — |
| A4-CI | 2 | CI, contract tests, merge gate | Agent 4 | BACKLOG | A1-CONTRACT | — |

## Next task

A1-BOOT (Agent 1). Complete the bootstrap PR and get it merged. Agents 2–4 remain read-only until A1-CONTRACT merges and their tasks are marked READY.

## Blocker (active)

This PC has no `git` installed and the local working directory is empty, so the coordination files below cannot be cloned from or pushed to the remote yet.

Smallest user action needed: install `git` on this PC, then clone `https://github.com/tanmay17-gif/Sidekick.git` into this directory (default branch `main`), create branch `agent1/bootstrap-protocol`, add the `.sidekick/` files, commit, push, and open a PR against `main`.

## Remote state (observed 2026-10-21)

- `https://github.com/tanmay17-gif/Sidekick.git` — public, empty (size 0), default branch `main`, no commits, no open issues/PRs.
- Local directory `C:\Users\Admin\Documents\Default Project` — empty; `git`, `node`, `npm` not installed; Python 3.13.14 present.