# Sidekick API Contracts

Request/response schemas, action lifecycle, and compatibility rules. Owned by Agent 1. API changes require review. Versioned.

## Version

Current contract version: `v1` (implemented, Phase 1). The HTTP surface lives in `sidekick/core/schemas.py`
and `sidekick/api/app.py`; this document describes exactly what is implemented.

Changes since the first draft of this document (additive, still `v1`):

- `response.status` may also be `needs_clarification` or `awaiting_transcript`.
- `decision_model` reports the provider, the model, the source and whether a fallback ran.
- actions carry `description`, `plan_hash`, `job_id` and `progress`.
- the error envelope gained `details`.
- events gained `kind`, `seq`, `ts`, `tool`, `status` and `job_id`.
- the response gained an optional `speech` string for the client to read verbatim.
- `correction_context` accepts the browser client's `signal` and `supersedes`;
  `continuation_context` accepts `previous_request_id`.
- the capability inventory (`GET /api/v1/capabilities`) carries both the browser vocabulary
  (`capabilities[].state`) and the execution vocabulary (`tools[].status`).

### Ratified proposals from the other agents

| Proposal | Source | Status |
|---|---|---|
| `action.job_id`, `action.progress` | Agent 2, `docs/execution-service-contract.md` §9 | ratified, optional |
| `error.details` | Agent 2, §9 | ratified, implemented |
| `action.result.outcome` (`succeeded`/`partial`/`failed`/`cancelled`) | Agent 2, §9 | ratified as a tool level field inside `result` |
| the `job.*` event shape | Agent 2, §4 | ratified: the core's events carry `type`, `kind`, `seq`, `ts`, `status`, `job_id` |
| endpoint paths `/api/v1/requests`, `/api/v1/capabilities`, `/api/v1/media/catalog`, `/api/v1/actions/:id` | Agent 3, `web/docs/CONTRACT_NOTES.md` §1 | ratified, implemented next to the `/v1/...` aliases |
| the capabilities response shape | Agent 3, §2 | ratified, both vocabularies in one response |
| `continuation_context.previous_request_id`, `correction_context.signal`, `correction_context.supersedes` | Agent 3, §4 | ratified, accepted |
| the optional `speech` string | Agent 3, §5 | ratified, optional |

`POST /api/v1/requests` may answer with `application/json` or, when the client asks for it, with
`text/event-stream` (one event frame per event, then the final response frame). Both are implemented.

## Session identity precedence

Explicit session ID via a validated request field or header. Precedence defined once: header wins if present, otherwise the validated body field. Defined once, applied everywhere.

The browser client sends `X-Sidekick-Session-Id`; `X-Sidekick-Session` is accepted as an alias. Implemented in `sidekick/api/app.py::create_app` and asserted by `tests/test_api.py`.

## Request

`POST /api/v1/requests` (alias: `POST /v1/decide`)

```json
{
  "request_id": "<stable UUID>",
  "session_id": "<explicit session ID>",
  "utterance": "<user transcript>",
  "input_source": "voice | text",
  "utterance_finalized": true,
  "correction_context": { ... optional ... },
  "continuation_context": { ... optional ... }
}
```

- `request_id` and `session_id` are required and stable.
- `utterance_finalized` indicates whether the transcript is final (ASR complete) or still revising. A
  request with `utterance_finalized: false` is never executed; the answer is `awaiting_transcript`.
- `correction_context` carries correction/continuation signals (e.g. "actually Spotify", "make that tomorrow").
  Fields: `replaces_request_id`, `target_action_id`, `kind`, `note`, `signal` (free-form marker),
  `supersedes` (the action id the correction replaces - browser alias of `target_action_id`).
- `continuation_context` carries `resume_task_id`, `elide_tool`, `note` and `previous_request_id`
  (sent by the browser on every follow-up).
- Unknown fields are rejected (`422 invalid_request`). Identifiers may not contain control characters.
- `request_id` is idempotent: repeating it replays the stored answer and adds a `request.replayed` event.

The endpoint answers with `application/json` by default. When the client sends
`Accept: text/event-stream` it answers with a stream: one `data: {event}` frame per event,
followed by one final `data: {SidekickResponse}` frame. Both forms are implemented and tested.

## Response

```json
{
  "contract_version": "v1",
  "request_id": "<UUID>",
  "session_id": "<UUID>",
  "intent": {
    "normalized": "<string>",
    "confidence": 0.0-1.0,
    "ambiguous": false,
    "entities": [ ... ],
    "multi_action": false,
    "source": "model | rule"
  },
  "action_plan": [ <action> ],
  "risk_level": "low | medium | high | irreversible",
  "decision_model": {
    "provider": "<name>",
    "model": "<name>",
    "source": "model | rule",
    "fallback_used": false,
    "fallback_reason": "<why the model was not used, or null>",
    "latency_ms": 0.0,
    "device": "cpu | cuda | null",
    "load_error": "<string | null>",
    "model_available": true
  },
  "status": "<action lifecycle status>",
  "clarification": null | { "question": "<string>", "options": [ ... ], "action_id": "<id>", "missing_arguments": [ ... ] },
  "events": [ ... streaming/progress events ... ],
  "session": { ... session projection ... },
  "message": "<human readable summary for the UI>"
}
```

`decision_model.fallback_used` is `true` **exactly when the interpretation was not produced by the
configured decision model**. That happens when the model is unavailable, times out, returns unusable
output, is not confident enough, or when the request was resolved by the deterministic control
grammar. `source` says which layer produced it: `model` or `rule`.

### Response status

`pending`, `awaiting_confirmation`, `running`, `paused`, `succeeded`, `failed`, `cancelled`,
`superseded`, plus the two turn level states `needs_clarification` and `awaiting_transcript`.

## Action

```json
{
  "action_id": "<stable UUID>",
  "tool": "<capability>",
  "arguments": { ... validated arguments ... },
  "approval_required": true,
  "state": "pending | awaiting_confirmation | running | paused | succeeded | failed | cancelled | superseded",
  "superseded_by": "<action_id> | null",
  "result": ...,
  "error": { "code": "...", "message": "...", "retryable": false, "timeout": false, "details": {} },
  "timestamps": { "created": "...", "updated": "..." },
  "description": "<the segment this action came from>",
  "plan_hash": "<fingerprint of tool + arguments>",
  "job_id": "<the execution job that carries this action - equal to action_id in the core>",
  "progress": 0.0
}
```

`job_id` and `progress` are the additive fields proposed by Agent 2 in
`docs/execution-service-contract.md` §9 and are ratified here. They are optional:
a core action that has no execution job simply omits them.

## Events

```json
{
  "type": "action.started",
  "kind": "progress | log | action_update | diff | result | error",
  "seq": 3,
  "at": "2026-10-21T09:15:22.481Z",
  "ts": "2026-10-21T09:15:22.481Z",
  "action_id": "<uuid>",
  "job_id": "<uuid>",
  "tool": "<capability>",
  "status": "<action state at the time of the event>",
  "message": "<human readable>",
  "data": {}
}
```

- `type` is the precise event name (`turn.received`, `model.decided`, `plan.created`,
  `action.started`, `action.succeeded`, `action.failed`, `action.cancelled`, `action.paused`,
  `action.superseded`, `action.ongoing`, `action.awaiting_confirmation`, `action.progress`,
  `task.paused`, `task.resumed`, `turn.deferred`, `request.replayed`).
- `kind` is the coarse category the UI switches on (the browser client's `ProgressEventKind`).
- `seq` is strictly increasing per session, starting at 1, with no gaps. `ts` mirrors `at`.

This is the union of the browser client's `ProgressEvent` (Agent 3) and the execution service's
event object (Agent 2, `docs/execution-service-contract.md` §4): `type`/`kind`/`seq`/`ts`/`tool`/
`status`/`job_id` are all present, so neither consumer has to change.

## Capability inventory

`GET /api/v1/capabilities` (alias `GET /v1/capabilities`)

The response carries both vocabularies the team uses, computed from the same source of truth:

```json
{
  "contract_version": "v1",
  "mode": "live",
  "capabilities": [
    { "id": "note.write", "state": "live", "detail": "backed by a real adapter" }
  ],
  "tools": [
    {
      "tool": "note.write",
      "description": "...",
      "arguments_schema": { "content": { "name": "content", "type": "string", "required": true } },
      "approval_required": false,
      "risk_level": "low",
      "status": "REAL",
      "status_detail": "backed by a real adapter",
      "simulated": false
    }
  ],
  "tool_count": 1,
  "status_counts": { "REAL": 1 },
  "any_simulated": false,
  "games": [],
  "providers": []
}
```

- `capabilities[].state` uses the browser vocabulary `live | simulated | unavailable | unconfigured |
  disconnected` (Agent 3, `web/docs/CONTRACT_NOTES.md` §2).
- `tools[].status` uses the execution vocabulary `REAL | SIMULATED | NOT_CONFIGURED | NOT_IMPLEMENTED`
  (Agent 2, `docs/execution-service-contract.md` §6).
- The UI renders these verbatim; it never upgrades a state on its own. A capability without an
  adapter is `unavailable` / `NOT_IMPLEMENTED`, never `live`.

## Action lifecycle

Transitions:
`pending → awaiting_confirmation → running → paused | succeeded | failed | cancelled`

- A correction supersedes an unexecuted plan before execution. Both the superseded and the
  replacing action stay in `action_plan` - nothing is silently dropped.
- For a running action that cannot be cleanly cancelled: the action becomes `paused` with
  `error.code = "cancellation_unsupported"` and a message that says the work may still be running.
  The action is **not** reported as cancelled, because it was not.
- Resume resumes the correct task; does not replay already-completed steps.
- Pending actions are exposed for cancellation and status reporting.
- `control.*` pseudo tools are core orchestration, not capabilities: `control.cancel`,
  `control.pause`, `control.resume`, `control.switch`, `control.status`, `control.confirm`,
  `control.reject`. They appear in `action_plan` together with the actions they affected.

## Capability catalog

`GET /v1/tools` publishes the catalog. Agent 2 registers adapters against it.

```json
{
  "name": "note.write",
  "description": "Write a note for the user so it can be read back later",
  "aliases": ["write a note", "take a note"],
  "risk": "low | medium | high | irreversible",
  "requires_approval": false,
  "reversible": true,
  "cancellable": true,
  "arguments": [
    {
      "name": "content",
      "type": "string | integer | boolean | enum | duration",
      "required": true,
      "description": "...",
      "enum": [],
      "default": null,
      "aliases": [],
      "minimum": null,
      "maximum": null,
      "capture": "none | quoted | remainder | auto"
    }
  ],
  "result_fields": ["path", "bytes"],
  "destinations": []
}
```

`capture` says where a text argument takes its value from:

- `quoted` - only an explicitly quoted or named value is accepted,
- `remainder` - the text that follows the tool alias,
- `auto` - quoted when available, otherwise the remainder,
- `none` - the value is only ever supplied by the caller.

### Adapter protocol (Agent 2)

```python
class ToolAdapter(Protocol):
    spec: ToolSpec

    def execute(self, action: Action, arguments: dict, context: ToolContext) -> ToolResult: ...
    def cancel(self, action_id: str) -> bool: ...
```

- `ToolResult(ok=..., data=..., error=..., ongoing=...)`. `ongoing=True` means the work continues in
  the background: the action stays `running` and the adapter reports the final outcome through
  `context.complete(result)`.
- `cancel` returns `True` only when the work actually stopped. `False` is not an error; the core then
  reports a best-effort stop with an explanation.
- A capability can be *declared* without an adapter (`ToolRegistry.declare`). It is visible to the
  model and the UI, and calling it fails honestly with `tool_unavailable`.

## Error model

```json
{
  "error": {
    "code": "<string>",
    "message": "<string>",
    "retryable": false,
    "timeout": false,
    "details": {}
  }
}
```

Codes: `invalid_request` (422), `not_found` (404), `conflict` (409), `unprocessable_entity` (422),
`service_unavailable` (503). Tool level failures use the same shape inside `action.error`, with
codes such as `tool_unavailable`, `tool_execution_error`, `intent_not_resolved`,
`missing_argument`, `ambiguous_argument`, `out_of_range`, `unknown_argument`, `unsafe_value`,
`cancellation_unsupported`.

Timeout behavior, retry/idempotency rules, and streaming/progress event shape are defined per tool/capability.

## Compatibility and versioning

- Semantic versioning. Additive changes are backward compatible; breaking changes require a new contract version plus review.
- The browser UI obtains truthful capability/status information from the contract; no UI-only assumptions encoded into the core.
- Unknown request fields are rejected so that a client typo fails loudly instead of being ignored.

## Endpoints

Two path families are served by the same handlers: `/api/v1/...` (the paths the
browser client uses by default) and `/v1/...` (shorter aliases).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/requests` (alias `/v1/decide`) | one user turn |
| `GET` | `/api/v1/capabilities` (alias `/v1/capabilities`) | capability inventory |
| `GET` | `/api/v1/media/catalog` | media assets (the core ships none; the browser falls back to the bundled film) |
| `GET` | `/api/v1/actions/{action_id}` | one action and its events |
| `GET` | `/api/v1/actions/{action_id}/events` | SSE stream of the action's events |
| `POST` | `/api/v1/actions/{action_id}/approve` (alias `/confirm`) | approve or refuse a pending action |
| `POST` | `/api/v1/actions/{action_id}/cancel` | cancel one pending or running action |
| `GET` | `/v1/sessions/{session_id}` | session state, tasks, actions |
| `GET` | `/v1/sessions/{session_id}/events` | session event log (including background events) |
| `GET` | `/v1/tools` | the raw capability catalog |
| `GET` | `/healthz` (aliases `/v1/health`, `/api/v1/health`) | liveness + truthful model status |
| `GET` | `/` | the Phase 1 slice page (placeholder UI, Agent 3 owns the real one) |

A confirmation binds to the exact action: send the `plan_hash` you received and the API rejects the
confirmation with `409 conflict` when the plan changed in the meantime.

### Live action events

`GET /api/v1/actions/{action_id}/events` is a `text/event-stream`. It emits one `data: {event}`
frame per event of that action, as the events happen - which is how a long running action (a timer,
a coding job) reports its completion to a voice client.

- `?after=<seq>` resumes the stream after a disconnect. Every later event is delivered, with no
  duplicates and no gaps, exactly like the execution service's stream.
- `?timeout=<seconds>` bounds how long the stream stays open (default 30 s). The stream also ends
  when the action reaches a terminal state.
- The last frame is always `data: {"action": {...}, "seq": <n>}` with the final action state, so a
  client that reconnects late still learns the outcome.

## Required examples

1. Simple request
2. "do X - no wait, do Y" correction (pre-execution and in-flight)
3. Two valid actions joined by "and then"
4. Ambiguous destination requiring clarification
5. Follow-up with omitted parameter
6. Interruption and resume
7. Rejected confirmation
8. Cancellation of a stale pending action

A correction must be resolved before stale destination execution; multi-action parsing returns every segment or explicitly reports ambiguity — it never silently loses actions.

All eight are covered by `tests/` (see `tests/test_intent.py`, `tests/test_lifecycle.py`,
`tests/test_safety.py`).
