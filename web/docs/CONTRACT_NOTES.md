# Contract notes for Agent 1 (Core Brain) - proposals from Agent 3

> **Status: ratified.** Agent 1 merged the proposals below into
> `.sidekick/API_CONTRACTS.md` (PR #9, `agent1/contract-compat`, merged
> 2026-10-21): the endpoint paths, the capabilities response shape, the
> `continuation_context.previous_request_id` / `correction_context.signal` /
> `correction_context.supersedes` fields and the optional `speech` string are
> all in the contract and implemented in `sidekick/api/app.py`. The client was
> re-verified against the merged core - see `EXPERIENCE.md`.
>
> This file is kept as the record of what was proposed and why, plus the
> fields Agent 1 added afterwards that the client also handles.

`.sidekick/API_CONTRACTS.md` defines the request, response, action and error
shapes. This client implements exactly those shapes and needs no changes to
them. The notes below cover the two things the contract did not yet pin
down, plus the endpoint paths the browser expects.

**These were proposals. Nothing here has been merged into the contract; the
contract remains Agent 1's to change.** (superseded by the note above)

## 1. Endpoint paths

The browser needs concrete paths. They are all configurable via
`VITE_SIDECKICK_*` environment variables so a later change is a one-line edit
in `web/src/lib/api/endpoints.ts` rather than a change across the UI.

| Purpose | Default path | Override |
|---|---|---|
| Submit an utterance | `POST /api/v1/requests` | `VITE_SIDECKICK_INTERPRET_PATH` |
| Capability inventory | `GET /api/v1/capabilities` | `VITE_SIDECKICK_CAPABILITIES_PATH` |
| Media catalog | `GET /api/v1/media/catalog` | `VITE_SIDECKICK_MEDIA_PATH` |
| Single action status | `GET /api/v1/actions/:id` | `VITE_SIDECKICK_ACTION_PATH` |

`POST /api/v1/requests` may answer with either:

- `application/json` - a complete `SidekickResponse`, or
- `text/event-stream` - a sequence of `data: {progress event}` frames followed
  by one final `data: {SidekickResponse}` frame.

Both are implemented and tested. The SSE form is what makes live progress
possible; the JSON form is the fallback.

## 2. Capabilities response

The contract defines the request/response shapes but not the capability
inventory, yet the interface needs it to label things honestly. Proposed
shape (`web/src/lib/api/types.ts`):

```jsonc
{
  "contract_version": "v1",
  "mode": "live",              // "live" | "stub" - lets the UI label a dev double
  "capabilities": [
    { "id": "music.play", "state": "unconfigured", "detail": "Needs a Spotify app id and user token." }
  ],
  "games": [
    { "id": "chess", "name": "Chess", "state": "live", "detail": "Full rules engine." }
  ],
  "providers": [
    { "id": "spotify", "name": "Spotify", "state": "unconfigured", "detail": "...", "requires_user_action": true }
  ]
}
```

`state` uses one of `live | simulated | unavailable | unconfigured | disconnected`.
The UI renders these verbatim - it never upgrades a state on its own.

## 3. Media catalog

`GET /api/v1/media/catalog` is optional. When present it can supply additional
open-licensed titles; when absent the client falls back to the film shipped in
the repository. A proposed entry:

```jsonc
{
  "id": "tears-of-steel",
  "title": "Tears of Steel",
  "credit": "Blender Foundation / MPEG (CC BY 3.0)",
  "license": "CC BY 3.0",
  "src": "https://archive.org/download/Tears-of-Steel/tears_of_steel_720p.mp4",
  "mime_type": "video/mp4",
  "subtitle_src": "/media/tears-of-steel/TOS-en.srt",
  "subtitle_label": "official English subtitles",
  "companion_rules": [
    { "pattern": "\\brobot\\b", "title": "Robotics mentioned", "reason": "..." }
  ]
}
```

The companion derives its events from the parsed cue list. `companion_rules`
are regular expressions matched against cue text; each rule produces at most
one event, at the real start time of the first matching cue.

## 4. Correction and continuation

The client sends:

- `continuation_context.previous_request_id` on every request that follows
  another one in the same session, so the backend can resolve a follow-up with
  an omitted parameter.
- `correction_context.signal` only when the utterance contains an explicit
  correction marker **and** the previous response still had a pending or
  running action.

The browser deliberately does not decide what a correction means. It flags the
signal; the decision engine resolves it. `web/src/state/useSidekick.ts` exports
`looksLikeCorrection` so the rule is visible and testable.

## 5. Speech output

The response may include an optional `speech` string. When it is present the
client speaks it verbatim. When it is absent the client reads a short summary
of the real action plan ("`music.play` completed."). No spoken text is
invented beyond that summary.
