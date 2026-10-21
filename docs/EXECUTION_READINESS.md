# Execution Readiness (Agent 2)

**Owner:** Agent 2 (Real Execution & Integrations)
**Scope:** the execution layer - coding-task execution, provider configuration,
job lifecycle, workspace safety, execution adapters.
**Branch:** `agent2/execution-foundation` (PR #4)

This is an honest readiness report. It separates what is *verified*, what is
*implemented but unverified*, what is *simulated*, and what is *not
configured*.

---

## 1. Readiness summary

| Capability | Readiness | Evidence |
|---|---|---|
| Workspace authorization and containment | **READY** | 24 sandbox/workspace tests + 7 containment regression tests |
| Command sandbox (allowlist, timeout, bounds, env scrub) | **READY** (process-level, see §5) | `docs/SANDBOX_THREAT_MODEL.md` |
| Real Git diff capture | **READY** | `tests/test_real_diff.py` (6 tests, after a defect was found and fixed) |
| Real test execution with the real exit code | **READY** | end-to-end through the core |
| Job lifecycle, approval chaining, cancellation | **READY** | `tests/test_job_lifecycle.py`, `tests/test_execution_adapter.py` |
| Restart recovery and event resume | **READY** | `tests/test_job_reliability.py` |
| Idempotent submission | **READY** | `tests/test_job_reliability.py::DuplicateRequestTests` |
| Truthful outcome reporting | **READY** | `tests/test_outcome_contract.py` |
| Core integration over HTTP + SSE | **READY** | `tests/test_core_integration.py` |
| HTTP/SSE and MCP transports | **READY** | `tests/test_transports.py` |
| **Coding agent against a real model** | **NOT VERIFIED - BLOCKED** | see §3 |

## 2. What the execution service does

```
utterance → core brain → safety policy → human approval
          → ToolAdapter (sidekick/tools/execution.py)
          → execution service (HTTP + SSE)
          → workspace authorization → provider → real file edits
          → real git diff → real test command → real exit code
          → back through the core → progress events → browser
```

## 3. The coding provider: configured, validated, and **not yet live**

### 3.1 The two supported configuration paths

**A. An OpenAI-compatible HTTP endpoint**

| Variable | Meaning | Validation |
|---|---|---|
| `SIDEKICK_LLM_API_KEY` | the bearer token | required for this provider; never logged, printed, returned in a capability report or put into an error |
| `SIDEKICK_LLM_BASE_URL` | the endpoint | must be `http`/`https`, must have a host, must not carry credentials |
| `SIDEKICK_LLM_MODEL` | the model id | must not be empty; reported as the real model identity |
| `SIDEKICK_LLM_TIMEOUT` | seconds | `0 < t <= 600` |

**B. An authorized local coding CLI**

| Variable | Meaning | Validation |
|---|---|---|
| `SIDEKICK_CODING_CLI` | the CLI to run | must resolve to an executable on `PATH` or in a known install directory |
| `SIDEKICK_CODING_CLI_ARGS` | JSON array of argument templates (`{task}`, `{workspace}`, `{context}`) | must be a JSON array of strings |
| `SIDEKICK_CODING_CLI_TIMEOUT` | seconds | `0 < t <= 600` |

`SIDEKICK_PROVIDER` selects `auto` (default), `http_api`, `local_cli` or
`simulated`. An unknown name is a **configuration error** that lists the
supported names - it never silently becomes `auto`.

### 3.2 The error taxonomy

| Situation | `error.code` | `retryable` | `timeout` |
|---|---|---|---|
| no key / no CLI | `provider_not_configured` | no | no |
| broken configuration | `provider_config_invalid` | no | no |
| the endpoint cannot be reached | `provider_unavailable` | yes | no |
| the credentials were rejected (401/403) | `provider_auth_failed` | no | no |
| rate limited (429) | `provider_rate_limited` (carries `retry_after`) | yes | no |
| the endpoint timed out (408/504 or a socket timeout) | `command_timeout` | yes | **yes** |
| a 5xx answer | `provider_error` | yes | no |
| another 4xx answer | `provider_error` | no | no |
| the answer could not be parsed | `provider_output_invalid` | no | no |
| the answer tried to escape the workspace | `provider_output_invalid` | no | no |

### 3.3 Provider output is data, never commands

Before anything is written, the plan is validated:

* at most `max_edits` (50) edits;
* every path must be **relative** and must not contain `..`;
* every payload must be at most `max_file_bytes` (256 KiB);
* every edit must carry content, a patch or a delete flag.

Then the edits are applied **only** through `Workspace.resolve_child`, which
enforces containment against the real (link-resolved) path.

### 3.4 The live acceptance procedure

```powershell
python scripts/live_provider_acceptance.py
```

The script:

1. creates a disposable Git repository with a **real** bug
   (`add()` subtracts) and a **real** failing test;
2. asks the real core to carry out the task, which routes through the real
   adapter to the real execution service;
3. shows the edits the provider proposed, the approval that was required and
   the files that were really changed;
4. runs the project's real test command and reports the real exit code;
5. prints the real diff.

| Exit code | Meaning |
|---|---|
| `0` | a **live** provider fixed the bug and the tests passed |
| `1` | a live provider ran but the result was not correct |
| `2` | **BLOCKED** - no live provider is configured, or the configured one is the simulated substitute |

The script never substitutes a fixture, and it never reports "passed" for a
simulated provider. The credentials are never printed - only the provider
name, the model id and whether a key is present.

### 3.5 The current status: **BLOCKED**

```
$ python scripts/live_provider_acceptance.py
provider      : http_api
model         : -
api key present: False
local CLI      : -
BLOCKED: no live coding provider is configured.
exit code 2
```

There is **no** `SIDEKICK_LLM_API_KEY` and **no** authorized local coding CLI
(`claude`, `codex`, `aider`, `cursor-agent`, `copilot`, `gemini`, `ollama` -
all absent) on any agent's machine. So:

* the **executor** - workspace checks, real edits, real diff, real test run,
  real exit code - is `REAL_AND_VERIFIED`;
* the **provider** - the code that calls a real model - is real, validated
  code that has **never been pointed at a real model**.

**Required to close this:** set `SIDEKICK_LLM_API_KEY` (any OpenAI-compatible
endpoint) or install an authorized coding CLI and set `SIDEKICK_CODING_CLI`.
Nothing else is needed.

## 4. Job reliability

### 4.1 What survives a restart

Set `SIDEKICK_JOB_STORE` to a file path to make the service durable.
`GET /v1/health` then reports `"durable": true`; without it the service
says `"durable": false` rather than pretending.

| State | Survives a restart? |
|---|---|
| the job record (identity, tool, arguments, state, result, error) | **yes** |
| the event log, with the sequence numbers | **yes** |
| the idempotency keys | **yes** |
| the running process of an interrupted job | **no** |
| the contents of a disposable workspace | **no** (unless the caller kept it) |

A job that was running when the process died is recovered as **`failed`**
with the error code `job_interrupted` and a message that says the work may
be **partially applied**. It is never reported as succeeded and it is never
silently resumed - the running command cannot be re-attached to.

### 4.2 Event ordering and resume

* `seq` is strictly increasing per job, starting at 1, with no gaps.
* Events are delivered in `seq` order.
* Exactly one terminal event per job, and it is the last one.
* `GET /v1/actions/{id}/events?after=<seq>` resumes from a cursor with no
  duplicates and no gaps - **including after a restart**, because the event
  log is persisted.
* A stream that is resumed past the last event of a finished job closes
  immediately instead of holding the connection open.

### 4.3 Duplicate submissions

`POST /v1/actions` accepts an optional `idempotency_key`. A repeated
request with the same key (and the same session) returns the **existing**
job with HTTP 200 instead of starting the work again. This works with or
without a durable store, because preventing a duplicate execution is a
correctness property, not a durability property.

### 4.4 Cancellation

* A job that has not started is cancelled immediately.
* A running job is asked to stop; the underlying process is terminated, then
  killed.
* If the process does not stop within the grace period, the result says so
  (`stop_requested: true`) - the service does not claim the job stopped.
* Cancelling a finished job is refused with `job_not_cancellable`.
* Cancelling an unknown job is a `404` with `job_not_found`.

### 4.5 Retention

Finished jobs and their events are pruned after a TTL
(`JobManager.prune`), and the store is bounded (`max_jobs`,
`max_events_per_job`). In-flight jobs are never pruned.

### 4.6 Failure injection

`tests/test_job_reliability.py` injects the failures that break real
systems and checks the **observable** result through the real HTTP API:
duplicate requests, client disconnects and reconnects, a service restart
during a running job, cancellation races, provider failures, and retention.

## 5. The sandbox

Full detail in **`docs/SANDBOX_THREAT_MODEL.md`**.

The short version: the sandbox is **process-level**. It enforces an
executable allowlist, refuses shell launchers, blocks destructive argument
patterns, contains the working directory, applies a hard timeout, bounds the
output, scrubs the child environment and redacts secrets. It is **not**
container-grade and **not** kernel-grade. No container runtime exists on any
agent's machine (Docker, Podman and WSL were all checked and none is
installed). The threat model lists the residual risks and the integration
path for a container.

Two real escape vectors were found and fixed in this milestone:

1. **A junction or symlink inside the workspace could redirect a write
   outside it.** The containment check was lexical only.
2. **`git apply --unsafe-paths` allowed a patch to write outside the
   repository.** The flag is gone.

A third defect was found by the same audit: **`git diff --binary=false` is an
invalid option**, so the tracked-file diff silently came back empty. Only
*new* files had ever appeared in a diff. A failed git command now raises
`vcs_error` instead of looking like "no changes".

## 6. Results that cannot be misinterpreted

Every coding job returns, at minimum:

| Field | What it distinguishes |
|---|---|
| `proposed_edits` | what the provider asked for |
| `applied_files` | what was really written |
| `changed_files` | what Git says differs from HEAD |
| `diff_state` | `changes` / `no_changes` / `unavailable` (a workspace with no repository is **not** "no changes") |
| `diff` | the real unified diff |
| `test_result.argv` | the test command that really ran |
| `test_result.exit_code` | its real exit code |
| `test_result.passed` | whether it passed |
| `test_result.counts` / `counts_available` | counts only when the runner printed them - never invented |
| `outcome` | `succeeded` / `partial` / `failed` / `cancelled` |
| `provider.level` / `provider.simulated` | whether a **real** model made the change |
| `error.code` | a stable, specific reason (`test_failed`, `command_timeout`, `provider_auth_failed`, `job_interrupted`, ...) |

A failed test is reported as state `failed` with `error.code = "test_failed"`
and the outcome `partial`. The real diff and the real test result stay
attached under `error.details.outcome`, so the failure is visible *and* the
user can see what was changed.

## 7. Known limitations

| # | Limitation | Impact | What would close it |
|---|---|---|---|
| L1 | The coding provider has never run against a real model. | The model step is unverified. | A credential or an authorized CLI (§3.5). |
| L2 | The sandbox is process-level. | Untrusted code is contained by policy, not by the kernel. | A container runtime (§5 of the threat model). |
| L3 | No CPU/memory/process limits on child commands. | A runaway command can exhaust the machine. | The same container work. |
| L4 | Child commands keep network access. | A command could exfiltrate workspace contents. | The same container work, with the network disabled. |
| L5 | The core's session state is in memory (Agent 1's layer). | A core restart loses the conversation. | Agent 1's work; the execution service is durable independently. |
| L6 | The execution service is a separate process. | A deployment must run and address it. | `SIDEKICK_EXECUTION_URL`; the core degrades honestly when it is absent. |
| L7 | No music provider. | Media control is limited to the local machine (real multimedia keys, real volume). | A lawfully supported provider with credentials - not implemented as a pretend integration. |
