# Sandbox and Workspace Threat Model (Agent 2)

**Owner:** Agent 2 (Real Execution & Integrations)
**Applies to:** `sidekick_execution/sandbox.py`, `sidekick_execution/workspace.py`,
`sidekick_execution/adapters/coding.py`
**Status:** current as of the production-readiness milestone

## 0. The one thing to read first

**This sandbox is process-level. It is not container-grade and it is not
kernel-grade isolation.**

No container runtime exists on any agent's machine: Docker, Podman and WSL
were all checked and none is installed. The execution service therefore
contains a command with *policy*, not with a kernel boundary. A command that
is allowed to run is a command that runs with the privileges of the user who
started the service.

Every statement below describes what the sandbox *does* enforce. The residual
risks are listed honestly in §6 and are not downgraded.

## 1. Trust boundaries

```
 ┌──────────────────────────────────────────────────────────────┐
 │ Sidekick core (Agent 1)                                       │
 │  - parses the utterance, applies the safety policy             │
 │  - owns the human approval                                    │
 └───────────────┬──────────────────────────────────────────────┘
                 │ HTTP/JSON + SSE   (trust: same host, same owner)
                 ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ Execution service (Agent 2)                                   │
 │  ┌────────────────────────────────────────────────────────┐  │
 │  │ Sandbox: allowlist, no shell, cwd containment, timeout │  │
 │  └────────────────────────────────────────────────────────┘  │
 │                 │                                             │
 │                 ▼                                             │
 │        provider (model or local CLI)                           │
 │        - untrusted output                                    │
 └──────────────────────────────────────────────────────────────┘
```

Two boundaries matter:

1. **Core → service.** The core is trusted. It is the approval authority.
2. **Provider → service.** The provider's output is **untrusted data**. It
   is never executed as a command and never allowed outside the workspace.

## 2. What the sandbox enforces

| Control | Where | How it is verified |
|---|---|---|
| Executable allowlist | `sandbox.py` | `test_workspace_safety.py::CommandSafetyTests` |
| No shell (`shell=False`, argument vector only) | `sandbox.py` | by construction; shell launchers are also refused |
| Shell launchers refused (`cmd`, `powershell`, `pwsh`, `bash`, `sh`, `wsl`, `env`, `xargs`, …) | `SHELL_LAUNCHERS` | `test_shell_launcher_is_refused` |
| Forbidden executables refused (`format`, `mkfs`, `diskpart`, `shutdown`, `reg`, `takeown`, `icacls`, `cipher`, `vssadmin`, `bcdedit`) | `FORBIDDEN_EXECUTABLES` | `test_executable_outside_allowlist_is_refused` |
| Destructive arguments blocked (`rm -rf`, `git reset --hard`, `git clean -fdx`, `git push --force`, `git branch -D`, `dd if=`, `mkfs`, `chmod -R 777`, …) | `DESTRUCTIVE_PATTERNS` | `test_destructive_git_command_is_blocked` and two more |
| Working directory containment | `sandbox.py` | the child's `cwd` is forced to the workspace |
| Hard timeout with terminate-then-kill | `sandbox.py` | `test_timeout_is_reported_honestly` |
| Bounded stdout/stderr with explicit truncation reporting | `sandbox.py` | `test_output_is_bounded_and_truncation_is_reported` |
| Scrubbed child environment (explicit allowlist) | `ENV_ALLOWLIST` | `test_environment_is_scrubbed` |
| Secret redaction in captured output | `CommandPolicy.redact` | `test_registered_secrets_are_redacted_from_output` |
| Cancellation terminates the process | `run_cancellable` | `test_cancellation_stops_a_running_command` |
| The provider's key is registered as a secret | `service.py` | the key never appears in a report, an error or a log |

## 3. What the workspace enforces

| Control | Where | How it is verified |
|---|---|---|
| A workspace path must be absolute, exist and be a directory | `workspace.py` | `test_relative_path_is_rejected_as_ambiguous`, `test_missing_directory_is_rejected`, `test_file_path_is_not_a_directory` |
| A workspace must be under an authorized root | `workspace.py` | `test_path_outside_allowed_roots_is_unauthorized` |
| `..` traversal cannot escape an authorized root | `workspace.py` | `test_traversal_out_of_authorized_root_is_unauthorized` |
| **A link or junction inside the workspace cannot redirect a write outside it** | `workspace.py` | `test_workspace_containment.py` |
| A provider plan cannot write outside the workspace | `adapters/coding.py` | `test_a_provider_plan_cannot_write_outside_the_workspace` |
| A patch cannot write outside the repository | `adapters/coding.py` | `test_a_patch_cannot_write_outside_the_repository` |
| The provider's edits are validated before anything is written | `providers/base.py` | `test_provider_config.py::ChangePlanValidationTests` |
| A non-disposable workspace is never deleted | `workspace.py` | `test_non_disposable_workspace_is_never_destroyed` |

### 3.1 The link/junction escape (fixed)

`Workspace.resolve_child` used to check containment **lexically** only. A
Windows directory junction (or a POSIX symbolic link) inside the workspace
pointing elsewhere therefore passed the check, and the write landed outside
the authorized root.

The check is now performed twice: once on the path as written, and once on
the **real** path after links and junctions are resolved. The regression test
uses a real junction, because a junction can be created without elevated
privileges while a symbolic link cannot.

### 3.2 The patch escape (fixed)

`git apply` was called with `--unsafe-paths`, which allows a patch to write
outside the repository. The flag is gone; `git apply` now refuses such a
patch by itself.

## 4. Approval

| Property | How it is enforced | Verified by |
|---|---|---|
| A consequential action needs a human confirmation | the core's safety policy (`risk=high` or `requires_approval`) | `test_the_utterance_is_resolved_to_an_authorised_action` |
| The confirmation binds to the exact action and plan | `plan_hash` in the core; `plan_hash` in the execution service's approval store | `test_approval_is_bound_to_the_exact_plan` |
| An approval expires | the approval store has a TTL | `test_expired_approval_is_refused` |
| An approval is single-use | the grant is consumed on use | `test_approval_is_required_to_run` |
| A cancelled or retried action cannot reuse an old approval | a retry creates a new action, and a new action has no grant | `test_a_declined_approval_never_reaches_the_execution_service` |
| The service refuses to run an unapproved action on its own | the service's own gate | `JobManager.submit` → `awaiting_confirmation` |

## 5. Provider output is data, never commands

A provider's answer is parsed into a `ChangePlan` and then:

1. **validated** - a bounded number of edits, relative paths that may not
   escape, bounded payloads, and every edit must carry content, a patch or a
   delete flag;
2. **applied** only through `Workspace.resolve_child`, which enforces
   containment;
3. **never** passed to a shell, an interpreter or a command line.

A patch is applied with `git apply`, which is given the workspace as its
working directory and is not allowed to use `--unsafe-paths`.

## 6. Residual risks

These are real and are not mitigated by the current design.

| # | Risk | Consequence | Mitigation today |
|---|---|---|---|
| R1 | **An allowed executable runs with the user's privileges.** | A malicious or buggy program on the allowlist can read the user's files, open sockets or spawn processes. | The allowlist is small and explicit; the default set is `git`, `python`, `pytest`, `node`, `npm` and a few read-only utilities. Anything else is refused. |
| R2 | **No kernel isolation.** | A command that escapes its sandbox is not contained by the operating system. | None. This is the gap a container would close (§7). |
| R3 | **No CPU, memory or process-count limits.** | A runaway command can consume the machine. | Wall-clock timeout only. |
| R4 | **Child processes keep the network.** | A command can exfiltrate workspace contents. | None. The service's own outbound access is bounded by the provider call; commands are not. |
| R5 | **The allowlist is per-process, not per-action.** | Any command that is allowed may be invoked for any action. | The action's workspace is always the child's working directory, so a command cannot easily reach another workspace by path. |
| R6 | **Windows line endings.** | A file written with `\n` in a repository with `core.autocrlf=true` differs from the committed blob in bytes, so the diff is non-empty even when the text is identical. | The diff reports the **byte** difference, which is the truth. `diff_state` distinguishes "changes" from "no changes". |
| R7 | **A disposable workspace is not destroyed automatically.** | Temporary directories can accumulate. | `WorkspacePolicy.destroy_disposable` exists and only ever deletes a workspace it created. |

## 7. The container integration path

If kernel-grade isolation is required, the intended change is:

1. install a runtime (Docker or Podman) on every machine that runs the
   service;
2. run every allowed command inside a container that mounts **only** the
   authorized workspace, with the network disabled by default and a memory,
   CPU and process limit applied;
3. keep the *same* `CommandPolicy` - the allowlist, the argument rules, the
   timeout and the output bound stay exactly as they are, because they are
   policy, not isolation;
4. replace the `subprocess.Popen` call in `CommandRunner.run` with the
   container invocation, and keep `CommandResult` unchanged so every caller
   and every test keeps working.

`CommandRunner` is the single place where a process is started, so this is a
contained change with a clear seam. Until such a runtime exists, the
documentation and the capability report continue to say **process-level**.

## 8. What is deliberately *not* claimed

* Not container isolation.
* Not kernel isolation.
* Not protection against a malicious program that is already on the
  allowlist.
* Not protection against resource exhaustion.
* Not protection against a child process that has network access.
