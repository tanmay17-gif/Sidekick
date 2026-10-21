# Sidekick Task Board

Phases, dependencies, assigned owner, acceptance criteria, next task. Owned by Agent 1. Status changes only through reviewed PRs or the agreed GitHub issue workflow.

## Current phase

Phase 1 — Contract and vertical slice. (Phase 0 recovery is complete: the coordination files and the
repository skeleton are on `main`.)

## Task states

`BACKLOG` → `READY` → `IN_PROGRESS` → `BLOCKED` → `IN_REVIEW` → `MERGED` → `VERIFIED`

A task is not `MERGED` until the real merge commit exists on the remote base. A task is not `VERIFIED` until its acceptance evidence passes on the integrated code.

## Tasks

| ID | Phase | Task | Owner | Status | Depends on | Acceptance criteria |
|---|---|---|---|---|---|---|
| A1-BOOT | 0 | Repository audit + team protocol / bootstrap PR | Agent 1 | MERGED | — | `.sidekick/` coordination files created and present on `main` (commit `1b80a0d`). *Note: pushed directly to `main` before the PR-only rule could be applied - no PR exists for it.* |
| A1-CONTRACT | 1 | Document + implement minimal request/action contract + first vertical slice | Agent 1 | IN_REVIEW | A1-BOOT | Contract schemas v1 implemented in `sidekick/core/schemas.py`; HTTP surface in `sidekick/api/app.py`; real vertical slice (`POST /v1/decide` → real local adapter → UI page); automated tests; PR open |
| A1-BRAIN | 2 | Intent / session / correction / orchestration behind contracts | Agent 1 | IN_REVIEW | A1-CONTRACT | Correction (pre-exec + in-flight), multi-action, session isolation, safety policy, model/fallback observability - implemented and tested in the A1-CONTRACT PR; needs review + merge to become MERGED |
| A1-MODEL | 2 | Real decision model integration + honest provenance | Agent 1 | IN_REVIEW | A1-CONTRACT | `convaiinnovations/laya` wired in with lazy load, timeout, invalid-output handling and observable fallback; measured with `scripts/eval_laya.py` |
| A2-AUDIT | 0 | Read-only execution/integration prerequisites inventory | Agent 2 | READY | — | Inventory of runtime/tool/adapter prerequisites |
| A3-AUDIT | 0 | Read-only UI/voice/media prerequisites inventory | Agent 3 | READY | — | Inventory of voice/UI/media prerequisites |
| A4-RULES | 0 | Verify current official hackathon rules; start test/CI plan | Agent 4 | READY | — | Source URLs, date checked, requirement text saved in repo |
| A2-EXEC | 2 | Real execution + integration adapters | Agent 2 | BACKLOG | A1-CONTRACT | Adapters registered against `ToolAdapter`; no adapter means an honest `tool_unavailable` |
| A3-UI | 3 | Design system + real voice/UI foundations | Agent 3 | BACKLOG | A1-CONTRACT | The slice page in `sidekick/api/static/index.html` is a placeholder for this |
| A4-CI | 2 | CI, contract tests, merge gate | Agent 4 | BACKLOG | A1-CONTRACT | The test command is `python -m pytest` (no network, no model weights needed) |

## Next task

A1-CONTRACT review and merge (Agent 1 authored the PR; Agent 4 is the merge gate once its checks
exist). After that: A1-BRAIN hardening - the remaining gaps are listed under "Open gaps" below.

## Open gaps (Agent 1, after the A1-CONTRACT merge)

- The confirmation flow is exposed over HTTP but the *voice* confirmation ("yes", "no") is currently
  only reachable as a control verb in the utterance; Agent 3 should send the explicit
  `POST /v1/actions/{id}/confirm` call so the binding to the exact action is guaranteed.
- Session state is in-memory only; a restart loses the conversation. Documented as a Phase 1 limit.
- The rule fallback is catalog driven and reliable, but it cannot resolve capabilities that have no
  alias in the catalog; every capability must therefore declare its aliases.

## Remote state (observed 2026-10-21)

- `https://github.com/tanmay17-gif/Sidekick.git` — public, default branch `main`, one commit
  (`1b80a0d`, the coordination files) before the A1-CONTRACT PR.
- This PC: `git` is installed at `C:\Program Files\Git\cmd` (not on `PATH` by default),
  Python 3.13.14 with `fastapi`/`uvicorn`/`pydantic`/`pytest` and the `laya` package installed.
  Node is **not** installed, which is why the core brain is Python.
- GitHub CLI (`gh`) is **not** installed. The repository API is reachable with the credentials that
  Git Credential Manager already holds for `github.com`.
