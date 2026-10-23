# Execution Service Contract (Agent 2 → Agent 1, Agent 3)

**Owner:** Agent 2 (Real Execution & Integrations)
**Status:** proposed — waiting for Agent 1 to ratify (or amend) into `.sidekick/API_CONTRACTS.md`
**Contract version implemented:** execution `v1`, aligned to API contracts `v1`

This document describes the boundary between the Sidekick core (Agent 1) and
the Sidekick execution service (Agent 2), and the event schema the browser UI
(Agent 3) renders.

It is **additive**: every field in `.sidekick/API_CONTRACTS.md` v1 is
implemented unchanged. Where this service adds a field or an endpoint, the
addition is marked. Agent 1 may fold the additions into
`.sidekick/API_CONTRACTS.md`; Agent 3 may rely on the event schema as written
because it is already implemented and tested.

---

## 1. Transport

Two equivalent surfaces over the same implementation:

| Surface | Use |
|---|---|
| HTTP + JSON (+ SSE) | the core and the browser UI |
| MCP (JSON-RPC 2.0 over stdio) | MCP hosts and assistants |

The boundary is language-neutral on purpose: the core may be written in any
language.

### 1.1 HTTP endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/health` | liveness + job counters |
| `GET` | `/v1/capabilities` | truthful capability report (see §6) |
| `POST` | `/v1/actions` | submit an action |
| `GET` | `/v1/actions` | list actions (`?session_id=` optional) |
| `GET` | `/v1/actions/{id}` | one action |
| `POST` | `/v1/actions/{id}/approve` | approve a pending action |
| `POST` | `/v1/actions/{id}/cancel` | cancel an action |
| `GET` | `/v1/actions/{id}/events` | SSE stream of job events |

**Submit** — `POST /v1/actions`

```json
{
  "tool": "coding.execute",
  "arguments": { "task": "...", "workspace": "C:\\abs\\path" },
  "session_id": "<optional>",
  "confirmation_token": "<optional, required for approval-gated tools>"
}
```

Response `202`:

```json
{
  "action": { "...contract v1 action..." },
  "confirmation": null
}
```

When the tool requires approval, `confirmation` is populated and the action
is in state `awaiting_confirmation`:

```json
{
  "action": { "state": "awaiting_confirmation", "...": "..." },
  "confirmation": {
    "action_id": "<uuid>",
    "confirmation_token": "<opaque>",
    "expires_at": 1764000000.0,
    "plan_hash": "<sha256 of the plan>",
    "reason": "coding.execute requires explicit approval before it can run."
  }
}
```

The client shows the confirmation to the user and, only if the user agrees,
calls `POST /v1/actions/{id}/approve` with the same token. The token is
single-use and expires.

## 2. Action shape

The action object is exactly the contract v1 action:

```json
{
  "action_id": "<uuid>",
  "tool": "coding.execute",
  "arguments": {},
  "approval_required": false,
  "state": "pending | awaiting_confirmation | running | paused | succeeded | failed | cancelled | superseded",
  "superseded_by": null,
  "result": null,
  "error": null,
  "timestamps": { "created": "...", "updated": "..." }
}
```

Two **additive** fields are present when they apply:

| Field | Type | Meaning |
|---|---|---|
| `job_id` | string | equal to `action_id` in this implementation; provided so a UI can use one identifier for both concepts |
| `progress` | number | `0.0`–`1.0` when the action reports a measurable progress fraction |

### 2.1 Legal transitions

```
pending ──▶ awaiting_confirmation ──▶ running ──▶ succeeded
   │                  │                    ├────▶ failed
   │                  │                    ├────▶ cancelled
   │                  │                    └────▶ superseded
   │                  ├────▶ cancelled
   │                  └────▶ superseded
   ├────▶ running
   ├────▶ cancelled
   └────▶ superseded
```

* An action that requires approval never reaches `running` without a valid
  confirmation token.
* A terminal action is never overwritten by a late worker result.
* `paused` is defined in the contract vocabulary but is **not produced by this
  service**: pausing an in-flight command is not safely implementable in a
  process-level sandbox. The core should implement pause/resume by choosing
  not to submit the action yet.

## 3. Error model

Identical to contract v1:

```json
{ "error": { "code": "...", "message": "...", "retryable": false, "timeout": false } }
```

`details` is an **additive** optional object inside `error` carrying
structured context (for example the real exit code of a test command). It
never contains secrets.

### 3.1 Error codes emitted by this service

| Code | Meaning |
|---|---|
| `workspace_invalid` | the workspace path is missing, relative, or ambiguous |
| `workspace_unauthorized` | the workspace is outside every authorized root |
| `workspace_not_found` / `workspace_not_a_directory` | the workspace path does not exist / is not a directory |
| `command_not_allowed` | the executable is not on the allowlist, or is a shell launcher |
| `command_timeout` | the command exceeded its limit and was terminated (`timeout: true`) |
| `command_failed` | the command exited non-zero |
| `command_cancelled` | the command was cancelled |
| `output_limit_exceeded` | output exceeded the configured bound |
| `destructive_action_blocked` | a destructive command was refused |
| `approval_required` / `approval_invalid` / `approval_expired` | approval gate outcomes |
| `provider_not_configured` | no coding provider is configured in this deployment |
| `provider_unavailable` | the configured provider could not be reached |
| `provider_error` | the provider failed while producing a change plan |
| `provider_output_invalid` | the provider output could not be parsed |
| `job_not_found` / `job_not_cancellable` / `job_interrupted` | job lifecycle outcomes |
| `test_failed` | the required tests failed |
| `no_changes_produced` | the provider returned an empty change plan |
| `edit_apply_failed` / `edit_outside_workspace` | a change plan could not be applied safely |
| `vcs_not_a_repository` / `vcs_error` / `diff_too_large` | version-control outcomes |
| `invalid_request` / `not_implemented` / `internal_error` | generic |

## 4. Event schema (for Agent 3)

`GET /v1/actions/{id}/events` is a `text/event-stream`. Each frame is:

```
id: <seq>
data: {"event_id": "...", "job_id": "...", "seq": 3, "ts": "...", "type": "job.progress", ...}

```

### 4.1 Event object

```json
{
  "event_id": "<uuid>",
  "job_id": "<uuid>",
  "action_id": "<uuid>",
  "seq": 3,
  "ts": "2026-10-21T09:15:22.481Z",
  "type": "job.status",
  "status": "running",
  "message": "Job is running.",
  "data": {}
}
```

| Field | Type | Notes |
|---|---|---|
| `event_id` | string | unique per event |
| `job_id` | string | equal to `action_id` in this implementation |
| `action_id` | string | present whenever the event relates to an action |
| `seq` | integer | **strictly increasing per job, starting at 1, no gaps** |
| `ts` | string | UTC ISO-8601, millisecond precision, `Z` suffix |
| `type` | string | see §4.2 |
| `status` | string | the action state at the time of the event (may be `null`) |
| `message` | string | human-readable, may be `null` |
| `data` | object | type-specific payload, may be `{}` |

### 4.2 Event types and ordering

| Type | When | `data` |
|---|---|---|
| `job.created` | the action was accepted | `{"tool": "...", "status": "pending"}` |
| `job.status` | the action changed state | `{"status": "<new state>"}` |
| `job.progress` | incremental progress | tool-specific (e.g. `{"argv": [...], "exit_code": 0, "passed": true}`) |
| `job.log` | a line of command output | `{"stream": "stdout" \| "stderr", "text": "..."}` |
| `job.result` | **terminal**: succeeded or cancelled | `{"status": "<state>", "result": {...}}` |
| `job.error` | **terminal**: failed | `{"status": "failed", "error": {...contract v1 error...}}` |

Guarantees:

1. `seq` is strictly increasing per job, starting at 1, with no gaps.
2. Events for a job are delivered in `seq` order.
3. **Exactly one** terminal event is emitted per job, and it is the last
   event for that job.
4. `job.result` is used for success **and** cancellation; `job.error` is used
   only for failure. `data.status` always carries the final state, so the UI
   does not have to infer it from the event type.
5. A client may pass `?after=<seq>` to resume a stream after a disconnect and
   will receive every later event, with no duplicates and no gaps.

### 4.3 Recommended UI mapping

| Event | UI behaviour |
|---|---|
| `job.created` | show the action as accepted |
| `job.status` | update the action's state badge |
| `job.progress` | update the progress line / activity text |
| `job.log` | append to the output panel (bounded) |
| `job.result` | show the result; `result.diff` and `result.changed_files` describe the real changes |
| `job.error` | show `error.message` and `error.code`; offer retry only when `error.retryable` is `true` |

## 5. Result payloads

### 5.1 `coding.execute`

```json
{
  "outcome": "succeeded | partial | failed | cancelled",
  "summary": "...",
  "workspace": "C:\\abs\\path",
  "changed_files": [ { "path": "src/app.py", "status": "modified" } ],
  "diff": "diff --git a/... (a real unified diff)",
  "diff_truncated": false,
  "head_sha": "<sha>",
  "provider": {
    "name": "local_cli",
    "level": "REAL | SIMULATED",
    "simulated": false,
    "available": true,
    "reason": "ok",
    "latency_ms": 812,
    "model": "..."
  },
  "test_result": {
    "argv": ["python", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
    "exit_code": 0,
    "passed": true,
    "stdout": "...",
    "stderr": "...",
    "duration_ms": 2310,
    "timed_out": false,
    "cancelled": false,
    "truncated": false,
    "counts": {},
    "counts_available": false,
    "summary": "All executed tests passed."
  }
}
```

Rules the UI can rely on:

* `outcome == "succeeded"` means the edits were applied **and** every
  required test command exited `0`.
* `outcome == "partial"` means real changes were applied but a required test
  failed or timed out. The action state is `failed` and `error.code` is
  `test_failed` or `command_timeout`. **Never render this as success.**
* `test_result.counts` is empty and `counts_available` is `false` when the
  runner did not print counts. The service does not invent counts.
* `diff` is the real unified diff of the resulting workspace, captured after
  the test run, so it matches the workspace's final state.

## 6. Capability report

`GET /v1/capabilities` returns what is *actually* available:

```json
{
  "tools": [
    {
      "tool": "coding.execute",
      "description": "...",
      "arguments_schema": { },
      "approval_required": false,
      "risk_level": "high",
      "status": "REAL | SIMULATED | NOT_CONFIGURED | NOT_IMPLEMENTED",
      "status_detail": "why it is not available, when it is not",
      "simulated": false
    }
  ],
  "tool_count": 5,
  "status_counts": { "REAL": 4, "NOT_CONFIGURED": 1 },
  "any_simulated": false,
  "provider": { "available": false, "level": "UNAVAILABLE", "reason": "not_configured", "detail": {} },
  "workspace_policy": { "allowed_roots": ["..."], "require_git": false, "allow_create": false }
}
```

Agent 3 should render `status` and `status_detail` verbatim. A tool whose
status is `NOT_CONFIGURED` must not be offered as a working button.

## 7. Tools

| Tool | Status in this deployment | Approval | Risk |
|---|---|---|---|
| `coding.execute` | `REAL` when a provider is configured, else `NOT_CONFIGURED` | configurable | high |
| `coding.run_tests` | `REAL` | no | low |
| `workspace.inspect` | `REAL` | no | low |
| `vcs.diff` | `REAL` | no | low |
| `vcs.commit` | `REAL` | no (per-call `approval_required` supported) | medium |
| `system.info` | `REAL` | no | low |
| `system.volume` | `REAL` on Windows, else `NOT_CONFIGURED` | no | medium |
| `system.media_control` | `REAL` on Windows, else `NOT_CONFIGURED` | no | low |
| `system.clipboard` | `REAL` on Windows, else `NOT_CONFIGURED` | no | medium |
| `system.open` | `REAL` on Windows, else `NOT_CONFIGURED` | no | medium |
| `web.fetch` | `REAL` | no | low |

`coding.execute` arguments:

```json
{
  "task": "string (required)",
  "workspace": "absolute path (required)",
  "context_files": ["relative/path.py"],
  "test_command": ["python", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
  "require_tests": true,
  "approval_required": false,
  "test_timeout_seconds": 300
}
```

### 7.1 Real local operating-system capabilities

`system.volume`, `system.media_control` and `system.clipboard` call **real
Windows APIs** through `ctypes` — no third-party packages, no simulated
provider:

| Tool | Real API used | Behaviour |
|---|---|---|
| `system.volume` | `waveOutGetVolume` / `waveOutSetVolume` (`winmm.dll`) | reads/sets the master system volume, `{"level": 0-100}`; reading returns `{"level": N, "changed": false}` |
| `system.media_control` | `user32.keybd_event` | sends a real multimedia key press: `play_pause`, `next`, `previous`, `stop`, `mute`, `volume_up`, `volume_down`. This drives **whatever player the user actually has running** — it is the honest way to do music control without a music-provider account. |
| `system.clipboard` | `user32` / `kernel32` clipboard API | reads or writes real clipboard text |
| `system.open` | `os.startfile` | opens a file or URL with the OS default handler |
| `vcs.commit` | `git add -A` + `git commit -F -` | creates a **real** commit; the message is passed on stdin so its text can never be mistaken for a command. Reports `{"committed": false, "reason": "no_changes"}` when there is nothing to commit. |

On a non-Windows host these report `NOT_CONFIGURED` with a reason and the
tool call returns `not_implemented` — they never pretend to work.

`system.info` reports which of these are actually usable on the machine, so
the UI can reflect reality.

### 7.2 Real web lookups

`web.fetch` performs a **real** HTTP(S) request and returns what the server
actually returned:

```json
{
  "url": "https://example.com/page",
  "status": 200,
  "ok": true,
  "headers": { "content-type": "text/html; charset=utf-8" },
  "body": "...",
  "bytes": 4096,
  "truncated": false,
  "content_type": "text/html; charset=utf-8"
}
```

Safety rules:

* only `http` and `https` are accepted — `file:`, `ftp:` and `data:` are
  refused, so the tool cannot be used to read local files;
* URLs carrying credentials are refused, and any URL that reaches an error
  payload has its userinfo stripped, so a password is never echoed back;
* the body is capped (`max_bytes`, default 512 KiB) and truncation is
  reported;
* a hard timeout applies to the connection and the read;
* an HTTP error status is reported as a **result** (`status`, `ok: false`,
  `error.code: "http_error"`), not as a silent empty success.

This needs no provider account, so it is `REAL`. It is the capability behind
"look this up for me" voice requests.

## 8. MCP surface

`python -m sidekick_execution mcp` speaks JSON-RPC 2.0 on stdio.

| Method | Result |
|---|---|
| `initialize` | `{"protocolVersion": "2025-11-25", "capabilities": {"tools": {...}}, "serverInfo": {...}}` |
| `notifications/initialized` | no response (it is a notification) |
| `tools/list` | the same tools as §7, with `inputSchema` |
| `tools/call` | `{"content": [{"type": "text", "text": "<json>"}], "isError": bool}` |
| `ping` | `{}` |

`tools/call` runs a real job and waits for it. `isError` is `true` when the
action did not reach `succeeded`. The JSON text payload is
`{"action": {...}, "result": {...}, "error": {...}}`.

## 8a. Core integration

The execution service is driven by the core brain through
`sidekick/tools/execution.py`, which implements the core's `ToolAdapter`
protocol over this HTTP/SSE surface. The identifier mapping, the approval
chaining, the event forwarding and the failure semantics are documented in
`docs/core-integration.md`.

## 8b. Provider configuration

The coding provider is the only part of the pipeline that needs a credential.
The configuration is parsed and validated once; a broken configuration never
silently falls back to a different provider.

| Variable | Meaning |
|---|---|
| `SIDEKICK_PROVIDER` | `auto` (default), `http_api`, `local_cli`, `simulated`. An unknown value is a configuration error that names the supported options. |
| `SIDEKICK_LLM_API_KEY` | The bearer token for an OpenAI-compatible endpoint. Never logged, printed, returned in a capability report or included in an error. |
| `SIDEKICK_LLM_BASE_URL` | The endpoint base URL. Must be `http`/`https` and must not carry credentials. |
| `SIDEKICK_LLM_MODEL` | The model id. Reported as the real model identity. |
| `SIDEKICK_LLM_TIMEOUT` | Seconds. Must be `0 < t <= 600`. |
| `SIDEKICK_CODING_CLI` | The authorized local coding CLI to run. |
| `SIDEKICK_CODING_CLI_ARGS` | A JSON array of argument templates (`{task}`, `{workspace}`, `{context}`). |
| `SIDEKICK_CODING_CLI_TIMEOUT` | Seconds, same bound as above. |
| `SIDEKICK_ALLOW_SIMULATED_PROVIDER` | `1` enables the simulated provider. It is refused when `SIDEKICK_ENV=production`. |

`GET /v1/capabilities` reports the active provider and the parsed
configuration under `provider` and `provider_config`. The configuration block
never contains the key - only `api_key_present`.

## 9. Proposed additions to `.sidekick/API_CONTRACTS.md`

Agent 1 owns that file. These are the additive proposals; none of them
changes an existing field.

1. **`job_id`** — an optional identifier for the execution-side job that
   carries an action. Equal to `action_id` today.
2. **`progress`** — an optional `0.0`–`1.0` progress fraction on an action.
3. **`error.details`** — an optional structured context object inside the
   error.
4. **`action.result.outcome`** — the distinction between `succeeded`,
   `partial`, `failed` and `cancelled` for a tool that can partially apply
   work. Today this is carried in `result.outcome`; the contract's `state`
   vocabulary is unchanged.
5. **Event schema** — the `job.*` event shape in §4, so that Agent 3's UI and
   Agent 4's contract tests have a written source of truth.

## 10. Verification

The implementation is covered by the repository's own suite:

```powershell
python -m unittest discover -s tests -t . -v
```

The end-to-end tests create a real Git repository, run a real provider
process, perform real file writes, capture a real `git diff`, and run the
project's real test command, asserting that the reported exit code matches.
See `docs/execution-prerequisites-audit.md` for the runtime inventory these
tests were written against.
