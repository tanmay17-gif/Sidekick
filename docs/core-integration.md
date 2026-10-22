# Core ↔ Execution Integration (Agent 2)

**Owner:** Agent 2 (Real Execution & Integrations)
**Status:** implemented, in review (branch `agent2/core-integration`)

How the core brain (Agent 1) and the execution service (Agent 2) fit
together, and what each side guarantees.

## 1. The shape of the integration

```
browser ──POST /api/v1/requests──▶ core brain (Agent 1)
                                        │
                                        │  intent → safety policy → approval
                                        ▼
                                 ToolRegistry
                                        │
                                 ExecutionServiceAdapter  (Agent 2)
                                        │  HTTP/JSON + SSE
                                        ▼
                                 execution service (Agent 2)
                                        │
                                        │  workspace checks → provider → real edits
                                        │  → real git diff → real test command
                                        ▼
                                 provider (HTTP API / local CLI / simulated)
```

The adapter is `sidekick/tools/execution.py`. It implements the core's
`ToolAdapter` protocol, so the core never imports the execution service's
implementation - it only knows the protocol.

The boundary is deliberately **language-neutral** (HTTP + JSON + SSE), so the
core could be rewritten in another language without touching the execution
service.

## 2. Identifier mapping

| Core | Execution service | Relationship |
|---|---|---|
| `action.action_id` | `action.action_id` | **different** ids. The core's id identifies the plan; the service's id identifies the job. |
| `action.job_id` | `action.action_id` | the service's job id is written into the core action's `job_id` field (a ratified contract field) |
| `action.state` | `action.state` | the same vocabulary; the adapter maps `succeeded`/`failed`/`cancelled` onto the core's `ActionStatus` |
| `action.result` | `action.result` | the service's result payload is passed through unchanged, so `diff`, `changed_files` and `test_result` reach the browser as they are |
| `action.error` | `action.error` | the service's contract-v1 error object is passed through; on failure the outcome (diff, test result) is attached under `error.details.outcome` so a failure is still visible |

## 3. Approval: chained, not bypassed

`coding.execute` changes files, so it is declared with
`requires_approval=True` and `risk=high`. The core's safety policy therefore
demands an explicit confirmation that binds to the exact action via
`plan_hash`.

The execution service has its own approval gate as well. The two are
**chained**:

1. The core asks the human and records the confirmation.
2. The core executes the action, which reaches the adapter.
3. The adapter submits the action to the execution service.
4. If the service asks for a confirmation (its own gate), the adapter hands
   the service the confirmation token **the service itself issued**, and
   records `approved_by: "core"` in the service's event stream as an audit
   trail.

The service is never asked to run an unapproved action on its own: without an
approval it stays in `awaiting_confirmation` and refuses to start. A caller
that reaches the service directly (MCP, HTTP) still has to obtain a
confirmation token from it.

The core's approval is *not* a bypass, because the adapter only forwards it
after the core's policy has collected the human's confirmation.

## 4. Progress events

The adapter opens the execution service's event stream
(`GET /v1/actions/{id}/events`) in a background thread and forwards every
event into the core through `ToolContext.progress`. The core logs them as
`action.progress` events, which the browser already receives through the
core's own `GET /api/v1/actions/{id}/events` endpoint.

The forwarding is lossless: the execution event's `type`, `seq`, `status` and
`data` are passed on in the `data` payload (`execution_event_type`,
`execution_seq`), so the browser can tell a real progress event from a
synthesised one.

The final outcome is reported through `ToolContext.complete`, which is the
core's "ongoing action finished" hook. `execute` returns
`ToolResult(ongoing=True)` immediately, so the action stays `running` in the
core until the real job finishes.

## 5. Failure and cancellation

| Situation | What the browser sees |
|---|---|
| the service is not configured | `tool_unavailable` - the capability is *declared*, not registered |
| the service cannot be reached | `execution_service_unavailable`, `retryable: true` |
| the required tests failed | state `failed`, `error.code = "test_failed"`, and the **real** diff and test result under `error.details.outcome` |
| the job was cancelled | state `cancelled` |
| the job could not be stopped in time | the service reports that the stop was *requested*; the adapter does not claim the job stopped |

A partial success is never rendered as a success: the action state is
`failed` and the error code says exactly what happened.

## 6. Capability reporting

The core's `/api/v1/capabilities` reports both vocabularies:

* `capabilities[].state` - the UI's `live | simulated | unavailable | …`
* `tools[].status` - the execution service's `REAL | SIMULATED | NOT_CONFIGURED | NOT_IMPLEMENTED`

An adapter may describe itself more precisely through an optional
`capability_status()` method. The execution service adapter uses it to report
what is *actually* behind it:

| Situation | `tools[].status` |
|---|---|
| the service is reachable and a real provider is configured | `REAL` |
| the service is reachable but the provider is the simulated one | `SIMULATED` |
| the service is reachable but no provider is configured | `NOT_CONFIGURED` |
| the service is not reachable | `UNAVAILABLE` |

The core never upgrades a state on its own.

## 7. The coding provider

The provider is the only part of the pipeline that needs a credential.

| Provider | Configuration | Truth level |
|---|---|---|
| HTTP API (OpenAI-compatible) | `SIDEKICK_LLM_API_KEY`, `SIDEKICK_LLM_BASE_URL`, `SIDEKICK_LLM_MODEL`, `SIDEKICK_LLM_TIMEOUT` | `REAL` when configured |
| Authorized local coding CLI | `SIDEKICK_CODING_CLI`, `SIDEKICK_CODING_CLI_ARGS`, `SIDEKICK_CODING_CLI_TIMEOUT` | `REAL` when installed |
| Simulated substitute | `SIDEKICK_ALLOW_SIMULATED_PROVIDER=1` | `SIMULATED` - refused in production |

The configuration is parsed and **validated** once
(`sidekick_execution/providers/config.py`). A broken configuration never
silently falls back to something else: it produces an
`UnconfiguredCodingProvider` that names the problems, and the capability
report shows `NOT_CONFIGURED` with the reason.

Provider output is treated as **data, never commands**:

* the number of edits is bounded;
* every path must be relative and must not escape the workspace;
* every payload is bounded in size;
* the plan is validated *before* anything is written;
* the edits are applied only through the existing workspace authorization and
  edit-application path.

The API key is never logged, printed, returned in a capability report, or
included in an error message.

### Error classification

| Situation | `error.code` | `retryable` |
|---|---|---|
| no key / no CLI | `provider_not_configured` | no |
| broken configuration | `provider_config_invalid` | no |
| the endpoint is unreachable | `provider_unavailable` | yes |
| the credentials were rejected (401/403) | `provider_auth_failed` | no |
| rate limited (429) | `provider_rate_limited` | yes |
| the endpoint timed out | `command_timeout` (`timeout: true`) | yes |
| a 5xx answer | `provider_error` | yes |
| a 4xx answer | `provider_error` | no |
| the answer could not be parsed | `provider_output_invalid` | no |

## 8. What is verified, and what is not

| Claim | Status |
|---|---|
| the core resolves an utterance to an authorised `coding.execute` action | `REAL_AND_VERIFIED` |
| the core's safety policy demands an approval for it | `REAL_AND_VERIFIED` |
| a declined approval never reaches the execution service | `REAL_AND_VERIFIED` |
| the action reaches the real execution service over HTTP | `REAL_AND_VERIFIED` |
| the job id maps onto the core action | `REAL_AND_VERIFIED` |
| progress events reach the core and the session | `REAL_AND_VERIFIED` |
| the files really change, the diff is the real diff | `REAL_AND_VERIFIED` |
| the test command really runs and its exit code is preserved | `REAL_AND_VERIFIED` |
| a failing test is reported as a failure with the real diff attached | `REAL_AND_VERIFIED` |
| cancellation reaches the real job | `REAL_AND_VERIFIED` |
| an unreachable service produces a retryable, honest error | `REAL_AND_VERIFIED` |
| the capability report states the truth | `REAL_AND_VERIFIED` |
| **the model decides the change** | **`REAL_BUT_UNVERIFIED`** - no credential or coding CLI exists on any agent's machine, so the provider mechanism is verified against a deterministic fixture and never against a real model |

The live-provider acceptance test is **skipped with a reason** when no
credential is configured. It is never replaced by a fixture that reports a
pass.
