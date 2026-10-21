# Execution & Integration Prerequisites Audit (Agent 2)

**Owner:** Agent 2 (Real Execution & Integrations)
**Task:** `A2-AUDIT` — read-only execution/integration prerequisites inventory
**Date:** 2026-10-21
**Status:** complete (read-only audit; no product code was changed to produce this document)

All findings below were produced by running commands on the machine that
produced this audit. Where a fact could not be verified, it says so.

---

## 1. Why this audit exists

Agent 1's `TEAM_PLAYBOOK.md` keeps Agents 2 and 3 read-only until the
bootstrap is merged and their tasks are `READY`. `A2-AUDIT` is the `READY`
Phase-0 task for Agent 2. Its acceptance criterion is an "inventory of
runtime/tool/adapter prerequisites".

This document is that inventory. It also records the decisions that the
inventory forced, so the team can review them.

## 2. Verified runtime inventory

Verified on the audit machine (Windows, `win32`) on 2026-10-21.

| Component | Status | Evidence (command actually run) |
|---|---|---|
| Git for Windows | **Installed**, 2.55.0.windows.5 | `git --version` → `git version 2.55.0.windows.5` |
| Git location | `C:\Program Files\Git\cmd\git.exe` | not on the process `PATH`; found by `Test-Path` |
| Python | **Installed**, 3.14.8 | `python -c "import sys; print(sys.version)"` |
| Python location | `C:\Users\Admin\AppData\Local\Programs\Python\Python314\python.exe` | `where.exe python` |
| Node.js | **Not installed** | `where.exe node` → not found |
| npm | **Not installed** | `where.exe npm` → not found |
| Docker | **Not installed** | no `docker.exe` under `C:\Program Files\Docker`; no `com.docker.service` |
| Podman | **Not installed** | `C:\Program Files\RedHat\Podman\podman.exe` absent |
| WSL | **Not installed** | `C:\Windows\System32\wsl.exe` absent |
| GitHub CLI (`gh`) | **Not installed** | `where.exe gh` → not found |
| GitHub REST API | **Reachable** | `GET https://api.github.com/repos/tanmay17-gif/Sidekick` → HTTP 200 |
| Git write auth | **Working** | `git push --dry-run` → exit 0; `git credential fill` returns a stored credential |
| PyPI | **Reachable** | `GET https://pypi.org/simple/pytest/` → HTTP 200 |
| nodejs.org | **Reachable** | `GET https://nodejs.org/dist/index.json` → HTTP 200 |
| Global `pip` | Present but slow to warm up | `python -m pip --version` |

### 2.1 Consequence: no container sandbox

No container runtime exists on this machine, and no agent may assume one
does. The execution sandbox is therefore **process-level**:

* executable allowlist, no `shell=True`, shell launchers refused;
* argument rules that block destructive and history-rewriting commands;
* working-directory containment inside the authorized workspace;
* hard timeout with terminate-then-kill escalation;
* bounded stdout/stderr with explicit truncation reporting;
* scrubbed child environment (explicit allowlist) and secret redaction.

This is a real boundary, but it is **not** a kernel-level boundary. If the
hackathon requires untrusted third-party code to run safely, a container or
microVM runtime must be added first. That is a deployment decision, not an
execution-code decision.

### 2.2 Consequence: the runtime choice

Node.js is absent on this machine, and Agent 4's independent audit of a
comparable machine also recorded "Node.js / npm: Not installed". Python 3.14
is present and works. The execution service is therefore implemented in
**Python 3 using only the standard library** — zero install step, so every
teammate can run it without a package install, and no dependency can drift
between the four machines.

The service is deliberately exposed over **HTTP + JSON (+ SSE) and MCP
(JSON-RPC)**, so the core implementation that Agent 1 writes is not tied to
this language. If Agent 1 chooses TypeScript for the core, the execution
service is reached over the same contract.

## 3. Coding-provider inventory

| Provider path | Status | Evidence |
|---|---|---|
| LLM HTTP API (OpenAI-compatible) | **Not configured** | no `SIDEKICK_LLM_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in the environment |
| Authorized local coding CLI | **Not installed** | `claude`, `codex`, `aider`, `cursor-agent`, `copilot`, `gemini`, `ollama` all absent from `PATH` |
| Local model server | **Not installed** | no `ollama` / `llamafile` |
| Local provider config files | **Absent** | no `~/.anthropic`, `~/.claude.json`, `~/.codex`, `~/.aider.conf.yml` |

### 3.1 Configuration is validated, never guessed

The provider configuration is parsed once and validated
(`sidekick_execution/providers/config.py`). A broken configuration produces an
`UnconfiguredCodingProvider` that *names the problems* instead of silently
falling back to a different provider. The checks are:

* an unknown `SIDEKICK_PROVIDER` is rejected and the supported names are listed;
* the base URL must be `http`/`https`, must have a host and must not carry credentials;
* the timeout must be `0 < t <= 600` seconds;
* the model name must not be empty;
* `SIDEKICK_CODING_CLI_ARGS` must be a JSON array of strings.

The API key is never logged, printed, returned in a capability report or
included in an error message - only `api_key_present` is published.

### 3.2 Consequence: honest labelling, no faking

Because no model credential or local coding CLI exists on this machine, the
coding workflow has two clearly separated halves:

| Half | What it does | Claim level |
|---|---|---|
| **Provider** (decides *what* to change) | HTTP API provider, local-CLI provider, or an explicitly-labelled simulated provider | `REAL` when a credential/CLI exists; `SIMULATED` for the dev substitute |
| **Executor** (does the change) | workspace validation, real file writes, real `git apply`, real `git diff`, real test command, real exit codes | `REAL` and verified on every run |

The executor half is fully exercised today. The provider half is real code
but cannot be exercised against a real model until a credential or a local
CLI is provided. The service reports that state precisely
(`provider_not_configured`) instead of pretending to be connected.

## 4. Version-control prerequisites

| Requirement | Status | Notes |
|---|---|---|
| `git` binary reachable from a scrubbed environment | **Met** | resolved via `PATH` plus a known-install-directory fallback (`C:\Program Files\Git\cmd`) |
| Working tree diff without touching the index | **Met** | `git diff` for tracked files, `git diff --no-index` for untracked files; `git add --intent-to-add` is deliberately *not* used so a user's index is never mutated |
| Initial commit in a disposable repository | **Met** | used by the end-to-end tests |
| Destructive history commands | **Blocked** | `git reset --hard`, `git clean -fdx`, `git push --force`, `git branch -D` are refused by the sandbox |

## 5. Test-runner prerequisites

| Requirement | Status | Notes |
|---|---|---|
| A test command that needs no installation | **Met** | the repository's own suite runs on `python -m unittest` (standard library) |
| Counts reported only when the runner prints them | **Met** | `unittest` prints `OK`/`FAILED`, not `N passed`; the service reports counts as unavailable rather than fabricating them |
| Exit status preserved verbatim | **Met** | covered by tests |

`pytest` is *not* installed on this machine. It is reachable from PyPI, but
the execution service must not depend on a package that is absent on a
teammate's PC, so the default test command uses the standard library.

## 6. Real local capabilities discovered

These were found by probing the machine with `ctypes` (no third-party
packages) and are now exposed as real tools:

| Capability | Real API | Status |
|---|---|---|
| System volume read/write | `waveOutGetVolume` / `waveOutSetVolume` (`winmm.dll`) | works; the master value is `0xFFFFFFFF` at 100% and must be masked to its 16-bit volume word |
| Multimedia key presses | `user32.keybd_event` | works — drives whatever player the user actually has running |
| System clipboard | `user32` / `kernel32` clipboard API | works (requires correct ctypes prototypes; a 32-bit default `restype` truncates the handle) |
| Open with the default handler | `os.startfile` | works on Windows |
| Audio devices | `waveOutGetNumDevs` | 1 device present |

None of these need a provider account, which is why they are marked `REAL`
rather than `NOT_CONFIGURED`. They are implemented in
`sidekick_execution/adapters/system.py` and covered by
`tests/test_system_capabilities.py`.

**Caveat for Agent 3:** these are *local machine* capabilities. They control
the machine Sidekick runs on. A music **provider** integration (Spotify,
YouTube Music, …) would still need an account and an API key — none is
configured — so this is genuine media control, not a streaming-service
integration.

## 7. Service-level prerequisites

| Requirement | Status | Notes |
|---|---|---|
| Long-running work needs a background worker | **Met** | `ThreadPoolExecutor` inside `JobManager` |
| Progress must reach the UI | **Met** | per-job event bus with monotonic sequence numbers and SSE transport |
| Cancellation must reach a running process | **Met** | the sandbox polls a cancel event and terminates the process tree |
| Restart recovery | **Met** | `JobStore` persists job records; jobs that were running when the process stopped are recovered as `failed` with `job_interrupted` |
| Secrets must not leak | **Met** | scrubbed child environment, secret redaction in captured output, tokens never included in public payloads |

## 8. Blockers and open questions

| # | Item | Impact | Smallest action that resolves it |
|---|---|---|---|
| B1 | No LLM credential or local coding CLI | The coding workflow cannot be exercised against a real model on any agent's machine | Provide one: set `SIDEKICK_LLM_API_KEY`, or install a coding CLI and set `SIDEKICK_CODING_CLI` |
| B2 | No container runtime | Untrusted third-party code cannot be isolated at kernel level | Decide whether the hackathon needs it; install Docker/Podman if so |
| B3 | Node.js absent | The core cannot be written in TypeScript on a machine without an install | Agent 1 decides the core stack; this service is reachable over HTTP/MCP either way |
| B4 | `gh` CLI absent | PR/issue automation needs the REST API | The REST API works with the stored Git credential; `gh` is a convenience, not a requirement |
| B5 | Alexa+ access unknown | Out of Agent 2's scope | Agent 4 is tracking this in `HACKATHON_REQUIREMENTS.md` |

## 9. What this unblocks

With this inventory settled, Agent 2 can implement the execution layer without
guessing:

* the runtime is Python 3 (standard library only);
* the sandbox is process-level, with the limits listed in §2.1;
* provider availability is reported honestly through a single provider
  interface, with no faked provider on the production path;
* the boundary to the rest of the product is a documented HTTP/SSE + MCP
  contract, so Agent 1 and Agent 3 can integrate in parallel.
