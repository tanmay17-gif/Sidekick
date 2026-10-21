# Handoff - Agent 1 (Core Brain & Architecture)

**Date:** 2026-10-21
**Role:** the core decision engine, the capability catalog, routing, the contracts, the trust
boundaries and the packaging.
**Status:** my work is complete and pushed. A single agent now owns the remaining development.

---

## 1. Branch and commits

| | |
|---|---|
| Branch | `agent1/capability-reality` |
| Tip | the handoff commit (this document). The commit before it is `d476a76` |
| Base | `main` @ `fcd2427b` (nothing has merged into `main` since PR #12) |
| Remote | `origin/agent1/capability-reality` - pushed and verified |

The branch's commits, oldest first:

| SHA | What it does |
|---|---|
| `eb34fa6` | the capability reality audit and the fixes it found (the false-success routing bug, the honest answers, the new capabilities, the client-capability declaration, the browser guard) |
| `c45aa4f` | the audit state, the integration questions and the next task (task board) |
| `4b3b92d` | packaging (the wheel check), routing hardening (four defects), the client trust boundary, the demo serving the built client |
| `d73c227` | the README points at the new verification scripts |
| `3c59b75` | the voice-first developer flow and the union with the execution service |
| `d476a76` | the developer path, the MCP reality and the merge order with PR #4 |
| (tip) | this handoff document |

Commits made **during the final handoff round**: `3c59b75`, `d476a76` and the handoff commit.

## 2. Pull request

| | |
|---|---|
| URL | https://github.com/tanmay17-gif/Sidekick/pull/13 |
| State | **open**, `mergeable: clean`, 6 commits before this handoff, 35 files |
| Checks | **none** - the repository has no CI on the Python side yet (Agent 4 owns that) |
| Reviews | none requested; the merge gate is Agent 4 |
| Body | updated with the merge order, the developer path, the MCP reality and the test results |

**I did not merge it, and I did not merge anyone else's PR.** PR #4 (Agent 2) and PR #1 (Agent 3)
are open and untouched by me.

## 3. Files changed and why

| File | Purpose |
|---|---|
| `sidekick/core/schemas.py` | contract v1 models: strict request/response/action/event, the `decision_model` provenance, the `speech` line, the `job_id`/`progress` fields Agent 2 proposed |
| `sidekick/core/catalog.py` | the capability catalog: content-word alias matching with a light stem, `tool_support()`, `destination_owners()`, `fuzzy_destination()` (typo tolerant, 4 characters minimum), `near_misses()`, the `label`/`owner`/`execution_target`/`capture` fields |
| `sidekick/core/engine.py` | the anchor (the model may not name a capability the utterance does not mention), the correction semantics, the control grammar, the capability discovery, the client-execution branch, the client sweeper, the project memory, the spoken summary |
| `sidekick/core/parsing.py` | segmentation (strong separators, sentence boundaries, a plain "and" only when both sides resolve), correction markers (middle vs trailing), control grammar, capability questions, time parsing (`parse_when`), the value capture that starts after the alias' content words |
| `sidekick/core/safety.py` | the deterministic policy: risk, approval, argument validation, the workspace containment (now excluding a tool's own location argument) |
| `sidekick/core/sessions.py` | session state: TTL, LRU eviction, bounded retention, the event log with a monotonic sequence, the per-session project |
| `sidekick/core/decisions/laya_model.py` | the real `convaiinnovations/laya` adapter: lazy load, two time budgets (cold start vs steady state), invalid-output detection, honest provenance |
| `sidekick/core/decisions/rule_model.py` | the deterministic catalog matcher (the fallback) |
| `sidekick/core/registry.py` | the `ToolAdapter` protocol Agent 2 implements, `ToolResult` with `ongoing`, the `ToolContext` completion/progress hooks |
| `sidekick/tools/local.py` | the real local adapters: notes, timers, `media.open` (a browser launcher), `web.search` (a real search results page), `reminder.set` (a real scheduled moment) |
| `sidekick/bootstrap.py` | the object graph; registers the execution service adapter when Agent 2's module is present, declares it otherwise; loads the client-capability manifest |
| `sidekick/api/app.py` | the HTTP surface: `/api/v1/requests` (JSON or SSE), `/api/v1/capabilities` (server side, client side, tools), `/api/v1/actions/{id}` + `/events` + `/complete` + `/approve` + `/cancel`, serving the built `web/dist` when it exists |
| `sidekick/client_capabilities.json` | **Agent 3 owns the content.** The declaration of the capabilities the browser client runs. The core only reads it. |
| `pyproject.toml` | the project-wide configuration: both packages, both console scripts, the dependencies and the extras |
| `scripts/check_packaging.py` | builds a wheel and checks that both packages and both scripts are in it |
| `scripts/check_contract_compat.py` | verifies the core against the *actual* contract files on the other agents' branches |
| `scripts/verify_backend.py` | 20 checks against a real uvicorn server over real HTTP |
| `scripts/reproduce_requests.py` | 13 realistic requests through the real application; the browser is stubbed unless `--real-browser` |
| `tests/*` | 198 tests: intent, routing, lifecycle, client contract, client lifecycle, developer flow, capabilities, packaging, contract compatibility, no browser side effects, and the opt-in real-model suite |
| `docs/CAPABILITY_REALITY_AUDIT.md` | the audit: what every capability really does, who owns the fix, what is explicitly not implemented |
| `docs/DECISION_FAILURES.md` | twelve reproducible failures with their root causes and the test that guards each |
| `.sidekick/*` | the contract, the architecture notes, the decision log (D17-D35) and the task board |
| `README.md` | the quickstart, the verification commands and the truth table |

## 4. Exact commands and results

| Command | Result |
|---|---|
| `python -m pytest tests/` | **198 passed, 7 skipped, 0 failed** (5.96 s) |
| `SIDECKICK_RUN_MODEL_TESTS=1 python -m pytest tests/test_laya_integration.py` | **6 passed** (the focused real-model suite) |
| `python scripts/verify_backend.py` | **20/20 passed, 0 failed** - a real uvicorn server, real HTTP, the real Laya model |
| `python scripts/check_contract_compat.py --agent2-branch origin/agent2/execution-foundation --agent3-branch origin/agent3/voice-experience` | **OK (11 checks)** against the latest heads of both branches |
| `python scripts/check_packaging.py --build` | **OK** - a real wheel containing `sidekick`, `sidekick_execution`, both console scripts and the static page |
| `python -m unittest discover -s tests -t .` (Agent 2's branch, in a temporary worktree) | **161 tests, OK** (89.6 s) |
| `git merge --no-commit --no-ff origin/agent2/execution-foundation` (test merge) | 4 conflicts, **all "take ours"** - my branch already contains PR #4's behaviour |
| Chrome process count before/after the suite | **0 windows opened** |

**Which tests are real and which are not**

| Kind | Examples |
|---|---|
| **Real backend over HTTP** | `scripts/verify_backend.py` - a real uvicorn process, real HTTP, the real Laya checkpoint, the real local adapters (a note really is written to disk) |
| **Real model** | `tests/test_laya_integration.py` (opt-in) - the real `convaiinnovations/laya` checkpoint on the CPU |
| **Real adapters, mocked browser** | the pytest suite - the notes and timers are real (real files, real background timers); only `webbrowser.open` is replaced, for the whole session, so no test can open a window |
| **Fixture / stand-in** | `tests/test_developer_flow.py` uses a stand-in coding adapter with the *same shape* as Agent 2's `coding.execute`. It tests the core↔adapter contract, **not** the execution service |
| **Not run here** | Agent 3's `npm run lint/typecheck/test/build` and Playwright - **Node.js is not installed on this machine**. Their own PR reports 138 unit + 23 Playwright green |
| **Not run here** | Agent 2's `scripts/live_provider_acceptance.py` - it needs a provider credential that does not exist. It exits `2` (BLOCKED) |

## 5. Known bugs, limitations and security risks

**Bugs I found and fixed in this branch** (all with regression tests): the model answering
confidently and arbitrarily; the model inventing a destination; every unsupported request
producing the same useless answer; "what can you actually do?" being unanswerable; a generic verb
hijacking a specific capability; an alias not matching across a filler word; a paraphrase choosing
the right capability but not finding its value; "at" being one edit from "yt"; a bare time naming
nothing; the anchor never filling in a missing capability; the quoted path captured as the task;
the core's containment check rejecting the tool's own project directory; the cold start reported as
a model timeout; a client capability able to hang forever; a client being able to claim a server
action; a test suite opening real browser windows.

**Limitations that remain (deliberate, documented)**

| Limitation | Where it is documented |
|---|---|
| The decision model's confidence is **not calibrated** for this answer space. The engine relies on the anchor (the answer must be supported by the utterance), not on the number. The `0.35` floor is a heuristic | `docs/DECISION_FAILURES.md` §12, `.sidekick/DECISION_LOG.md` D17 |
| A typo in a service name is resolved only for words of 4+ characters and only when the match is unambiguous | D30 |
| Session state is in memory: a restart loses the conversation | the task board |
| Reminders live in the running process; they are not delivered to a phone and are lost on a restart. The result says so (`delivery: "in-process; a restart loses the reminder"`) | the tool's own result |
| `web.search` opens the real results page. It does **not** read, summarise or verify the content. The result carries `kind: "search_results_page"` | the tool's own result |
| The core cannot verify that a browser really played a track. The client's report is the only evidence, so the capability is reported as `client`, never `live` | `docs/CAPABILITY_REALITY_AUDIT.md` §3, `.sidekick/API_CONTRACTS.md` |
| The core does not own a tool's project directory. A tool that declares a location argument authorises it itself; the execution service enforces its own allowed roots. The core's containment check still applies to every other path-like argument | `sidekick/core/safety.py` |

**Security notes**

- No secret is stored in the repository; the tree was scanned for token/key patterns (clean).
- The Laya API key, the provider key and the execution service URL are read from the environment
  and never logged or returned in a capability report.
- The safety policy can only *raise* risk. A model answer can never grant itself permission.
- An overruled model answer is reported as a fallback, so the provenance never claims the model
  decided something it did not.

## 6. Contract dependencies on the other two agents

**On Agent 2 (execution service) - PR #4, branch `agent2/execution-foundation` @ `39bccea6`**

| Dependency | Where |
|---|---|
| `ToolAdapter`: `execute(action, arguments, context) -> ToolResult` and `cancel(action_id) -> bool` | `sidekick/core/registry.py` - unchanged by me |
| `ToolResult(ok, data, error, ongoing)`: `ongoing=True` keeps the action `running` until `ToolContext.complete(result)` | `sidekick/core/registry.py` |
| `ToolContext.progress(message, data)` - the adapter's progress events reach the session and the browser | `sidekick/core/engine.py` |
| `action.job_id`, `action.progress`, `error.details`, `action.result.outcome` | ratified in `.sidekick/API_CONTRACTS.md` |
| An optional `capability_status() -> {"status", "detail"}` on the adapter; the core maps `REAL/SIMULATED/NOT_CONFIGURED/NOT_IMPLEMENTED` onto the browser's `live/simulated/unconfigured/unavailable` | `sidekick/api/app.py` |
| The `coding.execute` argument names (`task`, `workspace`) and the result payload | **open** - asked three times. The core works with the published names; the `workspace` is supplied from the session's project. |
| The remote provider path: `SIDEKICK_LLM_API_KEY` / `SIDEKICK_LLM_BASE_URL` / `SIDEKICK_LLM_MODEL` (an OpenAI-compatible endpoint, so nothing is installed on the user's machine) | their `providers/http_api.py` |
| The MCP transport: JSON-RPC 2.0 over stdio, `tools/list` + `tools/call`, over the same `ExecutionService` | their `sidekick_execution/mcp_server.py` - **it is an MCP host surface for the execution service, not a bridge to a third-party coding agent's MCP server** |

**On Agent 3 (browser client) - PR #1, branch `agent3/voice-experience` @ `680719e`**

| Dependency | Where |
|---|---|
| `POST /api/v1/requests` (JSON or SSE), `GET /api/v1/capabilities`, `GET /api/v1/actions/{id}`, `POST /api/v1/actions/{id}/approve`, `POST /api/v1/actions/{id}/cancel` | `sidekick/api/app.py` - the paths their `web/src/lib/api/endpoints.ts` uses |
| The session header `X-Sidekick-Session-Id` wins over the body field | `sidekick/api/app.py` |
| `capabilities[]` keeps **their** state vocabulary (`live/simulated/unavailable/unconfigured/disconnected`). The capabilities the client runs are in the new `client_capabilities[]` list, so their fixed `TONE_BY_STATE` map keeps working | `sidekick/api/app.py` |
| `POST /v1/actions/{id}/complete` with `{session_id, status, result, error}` - the client reports what really happened | `sidekick/core/engine.py` |
| The voice confirmation should call `POST /api/v1/actions/{id}/approve` with the returned `plan_hash` so it binds to the exact action | asked in the PR comment |
| `sidekick/client_capabilities.json` - **Agent 3 owns the content**; the core only reads it | `sidekick/bootstrap.py` |

## 7. Environment variables and credentials

None of them are in the repository; none of them are needed for the core's own test suite.

| Variable | Needed for | Status here |
|---|---|---|
| `SIDEKICK_LLM_API_KEY` (+ `_BASE_URL`, `_MODEL`) | the **remote/cloud** coding provider - the path where the user installs nothing on their machine | **not set anywhere.** This is the single blocker for a real coding task |
| `SIDEKICK_CODING_CLI` (+ `_ARGS`, `_TIMEOUT`) | the local coding CLI provider | no CLI is installed on any machine |
| `SIDEKICK_EXECUTION_URL` | pointing the core at Agent 2's execution service (default `http://127.0.0.1:8088`) | not set |
| `SIDEKICK_JOB_STORE` | a durable job store for the execution service | not set (the service then says `durable: false`) |
| `SIDEKICK_PROVIDER` | `auto` / `http_api` / `local_cli` / `simulated` | `auto` |
| `SIDEKICK_PROJECT_DIR` | the project a voice task runs in, when the user does not name one | optional |
| `SIDEKICK_WORKSPACE` | where the local tools write | defaults to `./sidekick_runtime` |
| `SIDEKICK_DECISION_MODEL`, `SIDEKICK_LAYA_CHECKPOINT`, `LAYA_PRELOAD` | the decision model | `auto` / `typed-decisions` / off |

## 8. Exact next steps for the single agent

1. **Merge PR #13 first, then PR #4, then PR #1.** The conflict between #13 and #4 resolves by
   taking #13's side (4 files: `.sidekick/TASK_BOARD.md`, `pyproject.toml`,
   `sidekick/api/app.py`, `sidekick/bootstrap.py`). Merge #4 into the result and re-run
   `python scripts/check_contract_compat.py` - it must stay at `OK (11 checks)`.
2. **Unblock the coding provider.** Set `SIDEKICK_LLM_API_KEY` for a remote OpenAI-compatible
   endpoint. Nothing is installed on the user's machine that way, which is what the milestone asked
   for.
3. **Run the live acceptance test** and record the real result:
   ```
   python scripts/live_provider_acceptance.py
   ```
   exit `0` = a live provider, through the real core, the real approval and the real execution
   service, fixed a real bug and the project's real test command passed. exit `2` = blocked. **Do
   not report a pass that was not observed.**
4. **Ask Agent 2 for** a `speech_template` for `coding.execute` (the core has no line to speak for
   a coding action) and the final `coding.execute` result payload; **Agent 3** for the argument
   names and result payload of `media.play`, `movie.play` and `game.start`, and whether the MCP
   surface must reach a third-party agent's MCP server. None of these block a merge.
5. **Add CI for the Python side** (Agent 4): `pip install -e ".[dev]"` then `python -m pytest`.
   The suite needs no network, no model weights and opens no browser windows. The wheel build and
   the real-model suite are the two opt-in jobs.
6. **Then, in order of value:** durable session storage (a restart still loses the conversation);
   a notification channel for the reminders; and the travel / food / Alexa+ / AWS work - each of
   which needs a provider, an account or a policy that does not exist yet. They are recorded in
   `docs/CAPABILITY_REALITY_AUDIT.md` §4 and must not be claimed.

## 9. Committed but not merged

Everything on `agent1/capability-reality` is committed and pushed but **not merged**:
the audit, the routing fixes, the packaging check, the client trust boundary, the developer flow
and the documentation. PR #13 carries all of it.

## 10. Changes I could not safely preserve or verify

| Item | Why |
|---|---|
| A live coding provider run | no credential exists on any machine. I have not run `live_provider_acceptance.py` as a pass, and I have not claimed one. |
| Agent 3's npm checks (lint, types, unit, build, Playwright) | **Node.js is not installed on this machine.** I ran their suite only as far as reading it, and their own PR reports it green. |
| The merged `main` behaviour of the three PRs together | no PR has been merged and the project owner has not authorised a merge. I test-merged PR #4 into my branch (4 conflicts, all "take ours") but did not create a merge commit. |
| The default branch | it is `main` now; `origin/HEAD` still points at the old `agent1/bootstrap-protocol` (a cosmetic remote setting, not a code problem). |
