# Sidekick API Contracts

Request/response schemas, action lifecycle, and compatibility rules. Owned by Agent 1. API changes require review. Versioned.

## Version

Current contract version: `v1` (draft, Phase 1).

## Session identity precedence

Explicit session ID via a validated request field or header. Precedence defined once: header wins if present, otherwise the validated body field. Defined once, applied everywhere.

## Request

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
- `utterance_finalized` indicates whether the transcript is final (ASR complete) or still revising.
- `correction_context` carries correction/continuation signals (e.g. "actually Spotify", "make that tomorrow").

## Response

```json
{
  "request_id": "<UUID>",
  "session_id": "<UUID>",
  "intent": {
    "normalized": "<string>",
    "confidence": 0.0-1.0,
    "ambiguous": false,
    "entities": [ ... ]
  },
  "action_plan": [ <action> ],
  "risk_level": "low | medium | high | irreversible",
  "decision_model": {
    "provider": "<name>",
    "model": "<name>",
    "fallback_used": false
  },
  "status": "<action lifecycle status>",
  "clarification": null | { "question": "<string>", "options": [ ... ] },
  "events": [ ... streaming/progress events ... ]
}
```

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
  "error": { "code": "...", "message": "...", "retryable": false, "timeout": false },
  "timestamps": { "created": "...", "updated": "..." }
}
```

## Action lifecycle

Transitions:
`pending → awaiting_confirmation → running → paused | succeeded | failed | cancelled`

- A correction supersedes an unexecuted plan before execution.
- For a running action that cannot be cleanly cancelled: stop/compensate safely and explain.
- Resume resumes the correct task; does not replay already-completed steps.
- Pending actions are exposed for cancellation and status reporting.

## Error model

```json
{
  "error": {
    "code": "<string>",
    "message": "<string>",
    "retryable": false,
    "timeout": false
  }
}
```

Timeout behavior, retry/idempotency rules, and streaming/progress event shape are defined per tool/capability.

## Compatibility and versioning

- Semantic versioning. Additive changes are backward compatible; breaking changes require a new contract version plus review.
- The browser UI obtains truthful capability/status information from the contract; no UI-only assumptions encoded into the core.

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