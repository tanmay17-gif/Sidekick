# Sidekick Team Playbook

Shared coordination protocol for the four-PC Sidekick build team. Owned by Agent 1 (Core Brain & Architecture). All agents must read before writing product code.

## 1. Roles (fixed)

| Agent | Role | Owns |
|---|---|---|
| Agent 1 | Core Brain & Architecture | `.sidekick/*` coordination files; intent/decision layer; session context; orchestration; policy; task board |
| Agent 2 | Real Execution & Integrations | Execution adapters, job lifecycle, tool/service adapters, safe workspace operations |
| Agent 3 | Product Experience | UI/design system, real voice I/O, media companion, music/game experiences, accessibility |
| Agent 4 | Integration, QA & Release | CI, contract tests, merge gate, hackatement evidence, release/deployment verification |

No agent may edit another agent's owned coordination file without a reviewed PR.

## 2. Git protocol (mandatory)

1. Never commit or push directly to the protected default branch (`main`). PR-only updates. Required CI checks must pass; no self-approval.
2. Work on an isolated feature branch with the assigned prefix: `agent1/`, `agent2/`, `agent3/`, `agent4/`. One task or tightly related change per PR.
3. Sync before every work session: `git status --short --branch`, `git remote -v`, `git fetch origin --prune`, `git log --oneline --decorate -12`, `git branch -vv`. Determine the actual default branch from GitHub/origin; never assume its name. Never discard uncommitted user work.
4. Before opening/updating a PR, fetch again and integrate the latest base into your feature branch (prefer merging latest base into an already-published feature branch over rewriting shared history). Do not force-push.
5. No destructive shortcuts: no `git reset --hard`, `git clean -fdx`, force-push, branch deletion, or overwriting another agent's work. Never resolve a conflict by blindly taking ours/theirs. Preserve user data.
6. Each PC has its own clone. GitHub commits/PRs are the shared source of truth, not a shared filesystem. Only claim an action (fetched, pushed, PR opened, merged, pulled) after the command/tool actually succeeded.
7. PR workflow: push only your feature branch; open/update a PR against the correct default branch; state base commit, scope, tests, limitations; request review from the affected owner. Do not merge your own PR. Agent 4 is the merge gate when its checks pass and permissions allow; if Agent 4 authored the PR, Agent 1 or the affected owner reviews it. Never bypass failing or required checks. If GitHub permissions prevent merging, report that plainly; do not imply it merged.
8. After a PR merges, fetch from origin and verify the merge commit is present on the remote base before starting any dependent task. A stale local checkout is not an acceptable reason to continue.
9. Conflicts: the file/module owner resolves behavior-level conflicts. Agent 4 coordinates integration. If a conflict changes an API/schema or crosses ownership boundaries, stop the merge, ask owners to agree on the contract, document the decision in `DECISION_LOG.md`, then proceed.
10. Secrets: never commit tokens, API keys, cookies, `.env`, credentials, private user data, generated dumps, or local machine-specific paths. Add `.env.example` with placeholder names only. Keep secrets out of logs, screenshots, PR descriptions, and test output.

## 3. First-start protocol (every session)

Work from the repository root and inspect, never assume:
- current Git remote, default branch, branch, status, and recent commits;
- existing files, tests, package managers, runtime versions, and architecture;
- available credentials/providers — check presence/status only, never print secret values;
- `.sidekick/` coordination documents, GitHub issues, open PRs, and task states;
- whether prior remote work exists (laptop loss does not prove the GitHub repository is empty).

If the repository is missing, the remote is wrong, GitHub auth is unavailable, or the branch/default branch cannot be identified: stop, report the exact blocker, and state the smallest user action needed. Never silently invent an alternate repository or pretend a push succeeded.

## 4. Coordination files and ownership

| File | Owner | Purpose |
|---|---|---|
| `.sidekick/TEAM_PLAYBOOK.md` | Agent 1 | Roles, Git protocol, statuses, merge rules |
| `.sidekick/ARCHITECTURE.md` | Agent 1 | Module boundaries and design decisions |
| `.sidekick/API_CONTRACTS.md` | Agent 1 | Request/response schemas, action lifecycle, compatibility rules |
| `.sidekick/TASK_BOARD.md` | Agent 1 | Phases, dependencies, owner, acceptance criteria, next task |
| `.sidekick/DECISION_LOG.md` | Agent 1 | Important decisions, alternatives, reasons |
| `.sidekick/INTEGRATION_STATUS.md` | Agent 4 | Current merged SHA, checks, blockers, next merge |
| `.sidekick/DEMO_TRUTH_TABLE.md` | Agent 4 | Demo claims mapped to real implementation and evidence |

Status changes only through reviewed PRs or the agreed GitHub issue workflow. Use GitHub issues/PR comments as the shared activity stream. If another agent already owns a file, do not create a competing version.

## 5. Task states and phase order

States: `BACKLOG` → `READY` → `IN_PROGRESS` → `BLOCKED` → `IN_REVIEW` → `MERGED` → `VERIFIED`.

A task is not `MERGED` until the real merge commit exists on the remote base. A task is not `VERIFIED` until its acceptance evidence passes on the integrated code. Only Agent 1 changes the overall phase/task ordering; Agent 4 records verification evidence. No agent may mark another agent's task done based only on a promise or PR description.

Phase map — nobody skips gates:
- Phase 0 — Recover and coordinate (this playbook + task board; Agent 4 verifies hackathon rules; Agents 2/3 read-only audits)
- Phase 1 — Contract and vertical slice (contracts + one real E2E slice with automated test; merge before parallel implementation)
- Phase 2 — Parallel foundation (intent/context/policy; execution adapters; design system + voice; CI/contract tests)
- Phase 3 — Real user experiences (voice → intent → execution; coding; media/subtitles; music; games)
- Phase 4 — Integrated hardening (multi-action, corrections, interruption, resume/switch, safety, session isolation, restart/reconnect, unavailable providers, permission denial)
- Phase 5 — AWS and open-source delivery (Bedrock where justified; deploy; docs; packaging)
- Phase 6 — Alexa+ and submission proof (access actually available; document limitations; no fake native claims)

A phase ends with its acceptance checklist, a merged commit, and an integration report — not a verbal assertion. Resequencing only through a documented decision on the task board.

## 6. Phase gating for Agents 2–4

Agents 2 and 3 may audit in read-only mode during Phase 0. They must not make product-code changes until:
- Agent 1's team protocol and initial architecture/contracts are merged, and
- the task board marks their tasks `READY`.

Agent 4 may research hackathon rules and CI during the read-only period.

## 7. Completion report for every task

Before declaring a task done, state in the PR/completion note:
1. Status (BLOCKED / IN_REVIEW / MERGED / VERIFIED — only what remote/test state supports)
2. Changes summary and paths owned
3. Git evidence: branch, commit SHA, PR link, actual merge SHA when applicable
4. Tests: exact command(s), pass/fail counts, exit codes; tests not run and why
5. Reality check: real vs. simulated vs. unverified/not configured; required secrets/devices/external access
6. Handoff: next READY task ID/owner, dependency satisfied, or exact blocker

## 8. Verified claim levels (used in docs/demo)

- `REAL_AND_VERIFIED` — end-to-end behavior actually exercised with evidence
- `REAL_BUT_UNVERIFIED` — code exists, but a required credential, device, API, or live test is missing
- `SIMULATED_TEST_ONLY` — a test double or development-only substitute
- `NOT_IMPLEMENTED` / `NOT_CONFIGURED` — unavailable or not wired up