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
| A1-CONTRACT | 1 | Document + implement minimal request/action contract + first vertical slice | Agent 1 | MERGED | A1-BOOT | Contract schemas v1 implemented in `sidekick/core/schemas.py`; HTTP surface in `sidekick/api/app.py`; real vertical slice; automated tests. Merged in #7 |
| A1-BRAIN | 2 | Intent / session / correction / orchestration behind contracts | Agent 1 | MERGED | A1-CONTRACT | Correction (pre-exec + in-flight), multi-action, session isolation, safety policy, model/fallback observability. Merged in #7, #9, #11 |
| A1-MODEL | 2 | Real decision model integration + honest provenance | Agent 1 | MERGED | A1-CONTRACT | `convaiinnovations/laya` wired in with lazy load, two time budgets, invalid-output handling and observable fallback; measured with `scripts/eval_laya.py` |
| A1-COMPAT | 2 | Cross-agent contract verification + live action event streaming | Agent 1 | MERGED | A1-CONTRACT | `scripts/check_contract_compat.py` verifies the core against the contract files on the Agent 2 and Agent 3 branches; `GET /api/v1/actions/{id}/events` streams an action's events live. Merged in #9 |
| A1-REALITY | 3 | Capability reality audit + the fixes it found | Agent 1 | IN_REVIEW | A1-BRAIN | `docs/CAPABILITY_REALITY_AUDIT.md` and `docs/DECISION_FAILURES.md`; the model may no longer name a capability the utterance does not mention; `web.search` and `reminder.set` added; capability discovery; honest unsupported answers; client-capability declaration; no test may open a browser. PR #13 open (`agent1/capability-reality`) |
| A1-HARDEN | 3 | Packaging, routing hardening, client trust boundary | Agent 1 | IN_REVIEW | A1-REALITY | The distribution contains both packages and both entry points (checked by building a wheel); the routing survives paraphrases, typos, corrections and context follow-ups; a client capability cannot be completed by the server, cannot hang forever and is never announced as done. PR #13 |
| A1-COVERAGE | 3 | Coding capability in `main` + the execution provider credential | Agent 2 | READY | A1-REALITY | `coding.execute` reaches `main` from `agent2/core-integration`; the *provider* still needs `SIDEKICK_LLM_API_KEY` or a coding CLI, otherwise the capability is `NOT_CONFIGURED` |
| A2-AUDIT | 0 | Read-only execution/integration prerequisites inventory | Agent 2 | MERGED | — | `docs/execution-prerequisites-audit.md` (PR #4) |
| A3-AUDIT | 0 | Read-only UI/voice/media prerequisites inventory | Agent 3 | MERGED | — | `web/docs/PREREQUISITES.md` (PR #1) |
| A4-RULES | 0 | Verify current official hackathon rules; start test/CI plan | Agent 4 | READY | — | Source URLs, date checked, requirement text saved in repo |
| A2-EXEC | 2 | Real execution + integration adapters | Agent 2 | IN_REVIEW | A1-CONTRACT | Implemented on `agent2/core-integration`; the provider credential is still missing |
| A3-UI | 3 | Design system + real voice/UI foundations | Agent 3 | IN_REVIEW | A1-CONTRACT | PR #1; the client capability declaration in `sidekick/client_capabilities.json` is Agent 3's to fill in |
| A4-CI | 2 | CI, contract tests, merge gate | Agent 4 | READY | A1-CONTRACT | The test command is `python -m pytest` (no network, no model weights needed) |


## Next task

PR #13 (Agent 1) - the capability reality audit, the routing hardening, the
packaging check and the client trust boundary. It is open and green:
`python -m pytest` -> 188 passed, 7 skipped; `python scripts/verify_backend.py`
-> 20/20 against a real uvicorn server with the real model;
`python scripts/check_contract_compat.py` -> OK (11 checks);
`python scripts/check_packaging.py --build` -> OK (a real wheel).
It needs the merge gate, not more work from me.

After it merges: **A1-COVERAGE** - Agent 2's `coding.execute` reaching `main`
**plus** the provider credential that is still missing. That credential is a
human decision (an LLM API key or a coding CLI); no agent can create it.

Not started, and deliberately so: durable session storage (a restart still
loses the conversation) and a notification channel for the reminders.

## Open integration questions (asked, with the request in the PR)

- **Agent 3** (PR #1): the argument names and the result payload for
  `media.play`, `movie.play` and `game.start`, and whether the shipped aliases
  in `sidekick/client_capabilities.json` should change. The file is theirs.
  Asked twice; no answer yet. The core works without it (the default
  arguments and the `awaiting_client` result are already in place), so this
  is not blocking.
- **Agent 2** (PR #4): the argument names `coding.execute` needs from an
  utterance (today: `task` and a quoted `workspace`), and the result payload
  the core should build a spoken line from. Asked twice; no answer yet. The
  core does not need it to route and approve the action.

## Open gaps (Agent 1, after the A1-REALITY merge)

- The confirmation flow is exposed over HTTP but the *voice* confirmation ("yes", "no") is currently
  only reachable as a control verb in the utterance; Agent 3 should send the explicit
  `POST /v1/actions/{id}/approve` call so the binding to the exact action is guaranteed.
- Session state is in-memory only; a restart loses the conversation. Within a running process the
  reconnect story is solid (`?after=<seq>` resumes an event stream without gaps). Documented as a
  Phase 1 limit.
- The confidence floor (`0.35`) is a **heuristic**, not a calibration. The model checkpoint is not
  calibrated for this answer space; the engine relies on the anchor (the model's answer must be
  supported by the utterance), not on the number.
- Reminders live in the core process. Pushing them to a phone needs a notification channel and an
  owner.
- Travel, food ordering and bookings have **no owner**. They need a real provider, an account and
  a money policy before the core may offer them.
 Declare them when the adapter exists.

## Remote state (observed 2026-10-21)

- `https://github.com/tanmay17-gif/Sidekick.git` — public, default branch `main`, one commit
  (`1b80a0d`, the coordination files) before the A1-CONTRACT PR.
- This PC: `git` is installed at `C:\Program Files\Git\cmd` (not on `PATH` by default),
  Python 3.13.14 with `fastapi`/`uvicorn`/`pydantic`/`pytest` and the `laya` package installed.
  Node is **not** installed, which is why the core brain is Python.
- GitHub CLI (`gh`) is **not** installed. The repository API is reachable with the credentials that
  Git Credential Manager already holds for `github.com`.
