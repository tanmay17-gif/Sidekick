# Sidekick Execution Service

Real task execution for [Sidekick](https://github.com/tanmay17-gif/Sidekick):
a coding agent that edits files inside an authorized workspace, runs real
commands and tests, captures real diffs, and reports honest outcomes.

Owned by **Agent 2 (Real Execution & Integrations)**.

## What this is

| Part | What it does | Truth level |
|---|---|---|
| **Executor** | workspace authorization, real file writes, real `git apply`, real `git diff`, real test command with the real exit code, job lifecycle, cancellation, progress events | **REAL** — verified by the test suite |
| **Provider** | decides *what* to change: an OpenAI-compatible HTTP API, an authorized local coding CLI, or an explicitly-labelled simulated substitute | **REAL** when a credential or CLI is configured; **SIMULATED** for the dev substitute |
| **Adapters** | MCP tool surface and HTTP/SSE API over the same tools, with a truthful capability report | **REAL** |

Nothing here fabricates a diff, a test result, or a provider answer. A
provider that is not configured produces a `provider_not_configured` error
and a capability report that says so.

## Requirements

Python 3.11+ (3.14 verified). **No third-party packages** — the service uses
only the standard library, so there is no install step on any teammate's
machine.

`git` is needed for diffs and patch application. It is resolved from `PATH`
and from the usual Windows install locations.

## Quick start

```powershell
# Truthful capability report
python -m sidekick_execution capabilities

# Real runtime capabilities of this machine
python -m sidekick_execution info

# HTTP + SSE service
python -m sidekick_execution serve --host 127.0.0.1 --port 8088

# MCP tool server over stdio
python -m sidekick_execution mcp
```

Submit a real coding action:

```powershell
$body = @{
  tool = "coding.execute"
  arguments = @{
    task = "Add a divide() helper to calculator.py"
    workspace = "C:\path\to\authorized\repo"
    context_files = @("calculator.py")
    test_command = @("python", "-m", "unittest", "discover", "-s", "tests", "-t", ".")
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8088/v1/actions `
  -ContentType "application/json" -Body $body
```

Watch progress:

```powershell
Invoke-WebRequest http://127.0.0.1:8088/v1/actions/<action_id>/events
```

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `SIDEKICK_ALLOWED_ROOTS` | `;`-separated list of directories actions may touch | current directory + temp dir |
| `SIDEKICK_DISPOSABLE_ROOT` | where disposable workspaces are created | system temp dir |
| `SIDEKICK_PROVIDER` | `auto`, `http_api`, `local_cli`, `simulated` | `auto` |
| `SIDEKICK_LLM_API_KEY` | key for an OpenAI-compatible endpoint | unset |
| `SIDEKICK_LLM_BASE_URL` | endpoint base URL | `https://api.openai.com/v1` |
| `SIDEKICK_LLM_MODEL` | model id | `gpt-4o-mini` |
| `SIDEKICK_CODING_CLI` | an authorized local coding CLI | unset |
| `SIDEKICK_CODING_CLI_ARGS` | JSON array of argument templates (`{task}`, `{workspace}`, `{context}`) | unset |
| `SIDEKICK_REQUIRE_APPROVAL` | `1` to require approval for every action | unset |
| `SIDEKICK_ALLOW_SIMULATED_PROVIDER` | `1` to enable the simulated provider (**dev only**) | unset |
| `SIDEKICK_ENV` | `production` disables the simulated provider entirely | unset |
| `SIDEKICK_JOB_STORE` | path to the job store used for restart recovery | unset (in-memory only) |

## Safety boundaries

* Executable allowlist; `shell=False`; shell launchers (`cmd`, `powershell`,
  `bash`, ...) refused.
* Destructive commands blocked: `rm -rf`, `git reset --hard`, `git clean -fdx`,
  `git push --force`, `git branch -D`, and more.
* Every path is validated against the authorized roots; `..` traversal and
  symlink escapes are refused.
* Hard timeout with terminate-then-kill escalation; cancellation is reported
  honestly, including when a process does not stop promptly.
* Bounded stdout/stderr with explicit truncation reporting.
* Child processes see a scrubbed environment; registered secrets are redacted
  from captured output.
* Approval grants are bound to one action and one plan hash, expire, and are
  single-use.

This is a **process-level** sandbox, not a container sandbox: no container
runtime was verified on the build machine. See
`docs/execution-prerequisites-audit.md`.

## Tests

```powershell
python -m unittest discover -s tests -t . -v
```

The end-to-end tests create a real Git repository, run a real provider
process, perform real file writes, capture a real `git diff`, and run the
project's real test command, asserting that the reported exit code matches.

## Documentation

* `docs/execution-prerequisites-audit.md` — the runtime/provider inventory
  (task `A2-AUDIT`).
* `docs/execution-service-contract.md` — the HTTP/SSE/MCP contract, the event
  schema for the UI, and the proposed additions to `.sidekick/API_CONTRACTS.md`.
