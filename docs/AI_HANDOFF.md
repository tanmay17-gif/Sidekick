# Sidekick — AI Handoff Document
_Last updated: 2026-10-23 | Branch: `integrated-sidekick` | Commit: TBD after push_

---

## 1. Product Purpose

Sidekick is a voice-first intelligent assistant that:
1. Understands natural-language requests (local Laya NLP model or deterministic rule engine)
2. Selects an appropriate capability from a typed registry
3. Checks safety constraints and requests human approval when needed
4. Executes supported actions through real local tools or a sandboxed execution service
5. Honestly reports success, failure, cancellation, and limitations

**It does not claim to perform actions it cannot verify.** Simulated capabilities are labelled; unconfigured providers report their status truthfully.

---

## 2. Repository & Git State

| Field | Value |
|---|---|
| **GitHub URL** | https://github.com/tanmay17-gif/Sidekick |
| **Local path** | `C:\Users\Mrunal Amkar\OneDrive\Documents\Sidekick` |
| **Active branch** | `integrated-sidekick` |
| **Remote** | `origin` → `https://github.com/tanmay17-gif/Sidekick` |
| **Remote sync** | Pushed to GitHub (`refs/heads/integrated-sidekick`) |
| **Base commit** | `d0cf516` (remediation commit tracks latest verified work) |

### Branches on Origin
- `main` — base trunk
- `integrated-sidekick` — active integration branch containing all unified work (supersedes PRs #1, #4, and #13)
- Older PR branches: `agent1/capability-reality` (PR #13), `agent2/core-integration` (PR #4), `agent3/voice-experience` (PR #1) — preserved for history but superseded by `integrated-sidekick`

---

## 3. Architecture Overview

```
User (Voice/Text)
      │
      ▼
[Frontend: React/Vite/TS]  ←──── web/ directory
  - Web Speech API (voice in/out)
  - Movie Buddy companion
  - Capability Bar / Control Room
      │
      │ HTTP (fetch, SSE)
      ▼
[Core Brain: FastAPI]  ←──── sidekick/ directory
  - /api/v1/requests  (intent + plan)
  - /api/v1/alexa     (Alexa Skills Kit)
  - /api/v1/capabilities
  - /api/v1/actions/{id}/complete  (client-executed actions)
      │
      ├──[Decision Engine]  sidekick/core/engine.py
      │     - LayaDecisionModel (local NLP, primary)
      │     - BedrockDecisionModel (AWS optional)
      │     - RuleDecisionModel (deterministic fallback)
      │
      ├──[Tool Registry]  sidekick/core/registry.py
      │     - NoteWriteTool, NoteReadTool (real file I/O)
      │     - TimerSetTool, TimerListTool (real in-memory timers)
      │     - MediaOpenTool, WebSearchTool, ReminderSetTool
      │     - Client capabilities (movie.play, game.start) — browser executes
      │     - coding.execute — forwarded to Execution Service
      │
      ├──[Safety Policy]  sidekick/core/safety.py
      │     - Workspace boundary enforcement
      │     - Risk levels: low / medium / high
      │     - Approval gates with plan_hash verification
      │
      └──[Session Store]  sidekick/core/sessions.py

[Execution Service: Python stdlib HTTP]  ←── sidekick_execution/ directory
  - Jobs, approval store, workspace policy, sandbox
  - Providers: Bedrock (AWS), HTTP API (OpenAI-compat), local CLI, simulated
  - MCP stdio server (JSON-RPC 2.0, protocol v2024-11-05)
  - git diff, test runner integration
```

---

## 4. Key Directories and Files

| Path | Role |
|---|---|
| `sidekick/` | Core brain package |
| `sidekick/api/app.py` | FastAPI application factory |
| `sidekick/api/alexa.py` | Alexa Skills Kit adapter |
| `sidekick/bootstrap.py` | Object-graph wiring (registry → engine → app) |
| `sidekick/core/decisions/` | Decision models (laya, bedrock, rule) |
| `sidekick/core/engine.py` | Request handling pipeline |
| `sidekick/core/safety.py` | Safety policy and approval logic |
| `sidekick/core/sessions.py` | Per-session state store |
| `sidekick/tools/local.py` | Local tool implementations |
| `sidekick/tools/execution.py` | HTTP adapter to execution service |
| `sidekick/client_capabilities.json` | Browser-side capabilities (movie, game) |
| `sidekick_execution/` | Execution service package |
| `sidekick_execution/service.py` | ExecutionService orchestrator |
| `sidekick_execution/providers/` | Coding providers (bedrock, http_api, local_cli, simulated) |
| `sidekick_execution/providers/bedrock.py` | **NEW** Bedrock coding provider (AWS auth only) |
| `sidekick_execution/mcp_server.py` | MCP stdio server |
| `sidekick_execution/sandbox.py` | Subprocess execution sandbox |
| `web/` | React/Vite/TypeScript frontend |
| `web/src/App.tsx` | Root application component |
| `web/src/components/MovieBuddy.tsx` | Movie Buddy companion |
| `web/src/lib/voice/` | Web Speech API wrapper |
| `web/src/lib/api/` | Backend client, types, endpoints |
| `web/dev/stub-server.mjs` | Local stub server for frontend dev |
| `tests/` | Python test suite |
| `scripts/` | Verification and evaluation scripts |
| `docs/` | Project documentation |
| `.env.example` | All env vars with placeholder values |

---

## 5. Request Flow (Complete)

```
1. User speaks/types → Frontend sends POST /api/v1/requests
2. Core validates → session_id, request_id, utterance
3. Decision Engine → picks primary model (Laya > Bedrock > Rule fallback)
4. Model returns → tool name, destination, confidence, is_correction
5. Safety Policy → checks risk level, workspace boundaries
6. If HIGH risk → returns action_plan with state=pending_approval
7. User approves (with plan_hash) → POST /api/v1/requests (confirmation)
8. If execution_target=client → action state=pending, frontend executes
   Frontend reports → POST /api/v1/actions/{id}/complete
9. If execution_target=server → ExecutionServiceAdapter POSTs to sidekick_execution
10. Execution service → runs provider (Bedrock/HTTP/CLI), applies diff, runs tests
11. Result flows back → SSE events + final response JSON
12. Frontend renders → honest success/failure/cancellation state
```

---

## 6. Environment Variables

### Required for Basic Operation (none — runs locally out of the box)
The application starts without any environment variable. The Laya NLP model (convaiinnovations/laya) is downloaded automatically on first run.

### Optional — Decision Model
| Variable | Default | Purpose |
|---|---|---|
| `SIDEKICK_DECISION_MODEL` | `auto` | `auto` \| `laya` \| `bedrock` \| `rule` |
| `SIDEKICK_WORKSPACE` | `./sidekick_runtime` | Workspace for notes, timers |

### Optional — AWS Bedrock (Decision Routing)
| Variable | Purpose |
|---|---|
| `AWS_ACCESS_KEY_ID` | AWS key for Bedrock access |
| `AWS_SECRET_ACCESS_KEY` | AWS secret for Bedrock access |
| `AWS_REGION` | AWS region (default: us-east-1) |
| `BEDROCK_MODEL_ID` | Model ID (default: anthropic.claude-3-sonnet-20240229-v1:0) |

> **IAM roles and profiles are also supported.** No separate API key needed.

### Optional — Alexa
| Variable | Purpose |
|---|---|
| `ALEXA_SKILL_ID` | Validate incoming Alexa requests (unset = no validation) |

### Optional — Coding Execution Service
| Variable | Purpose |
|---|---|
| `SIDEKICK_EXECUTION_URL` | URL of execution service (default: not running) |
| `SIDEKICK_PROVIDER` | `auto` \| `bedrock` \| `http_api` \| `local_cli` \| `simulated` |
| `SIDEKICK_LLM_API_KEY` | API key for OpenAI-compatible remote provider |
| `SIDEKICK_LLM_BASE_URL` | Base URL for remote provider |
| `SIDEKICK_LLM_MODEL` | Model name for remote provider |
| `SIDEKICK_CODING_CLI` | Path to local coding CLI (e.g. `claude`) |

### Optional — Frontend / Movie Buddy
| Variable | Purpose |
|---|---|
| `VITE_SIDECKICK_COMMENTARY_ENDPOINT` | Optional remote commentary model endpoint |
| `VITE_SIDECKICK_COMMENTARY_API_KEY` | Optional bearer token for commentary endpoint |

---

## 7. How to Run on Windows (PowerShell)

### Backend
```powershell
# From repository root
python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

### Frontend (development)
```powershell
cd web
npm install   # only needed once
npm run dev   # starts on http://localhost:5173 with proxy to port 8000
```

### Full integrated demo (backend serves built frontend)
```powershell
# 1. Build frontend
cd web; npm run build; cd ..

# 2. Start backend (serves web/dist/ at /)
python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8000

# 3. Open http://127.0.0.1:8000/
```

### Execution Service (optional, for coding.execute)
```powershell
python -m sidekick_execution --host 127.0.0.1 --port 8088
# Then set SIDEKICK_EXECUTION_URL=http://127.0.0.1:8088 for the core
```

### MCP Server (for Claude Code / Cursor integration)
```powershell
python -m sidekick_execution mcp
# Speaks JSON-RPC 2.0 on stdio
```

---

## 8. Test Commands and Results (Session 2026-10-23)

| Command | Passed | Failed | Skipped | Status |
|---|---|---|---|---|
| `python -m pytest` | 382 | 0 | 7 | ✅ PASS |
| `python scripts/check_packaging.py --build` | OK | — | — | ✅ PASS |
| `python -m pytest tests/test_core_contract.py tests/test_contract_compat.py tests/test_execution_contract.py -v` | All passed | 0 | — | ✅ PASS |
| `cd web && npm run lint` | 0 errors | — | — | ✅ PASS |
| `cd web && npm run typecheck` | 0 errors | — | — | ✅ PASS |
| `cd web && npm run test` | 162 | 0 | — | ✅ PASS |
| `cd web && npm run test:e2e` | 27 | 0 | — | ✅ PASS |
| `cd web && npm run build` | Built successfully | — | — | ✅ PASS |

**All checks green. 382 Python tests + 162 Vitest tests + 27 Playwright E2E tests = 571 automated tests passing.**

---

## 9. The No-Hosted-Key Requirement — Root Cause & Fix

### Root Cause Traced
The system was implicitly requiring `SIDEKICK_LLM_API_KEY` for the coding execution provider (`HttpApiCodingProvider`). When `auto` provider selection ran, the HTTP API provider was the first candidate checked; without a key it reported `not_configured` but the error messaging said "Set SIDEKICK_LLM_API_KEY". This created the impression that the app needed a key to function.

**The actual decision engine and all local tools never required a key.** The confusion originated in:
1. `sidekick_execution/service.py` `_coding_status()` message mentioning only `SIDEKICK_LLM_API_KEY`
2. `sidekick_execution/providers/http_api.py` hint text pointing only at `SIDEKICK_LLM_API_KEY`
3. No Bedrock coding provider existed (only the decision-model Bedrock existed)

### Fixes Applied
1. **Created `sidekick_execution/providers/bedrock.py`** — `BedrockCodingProvider` using standard AWS credential chain (no LLM API key). Status reason matches existing vocabulary (`not_configured`).
2. **Updated `sidekick_execution/providers/config.py`** — Added `bedrock` to `SUPPORTED_PROVIDERS`.
3. **Updated `sidekick_execution/providers/__init__.py`** — Exported `BedrockCodingProvider`.
4. **Updated `sidekick_execution/service.py`** — Added `bedrock` to `select_provider()` with priority before `http_api`. Updated `_coding_status()` message to list all three options: Bedrock (AWS), HTTP API (key), local CLI.
5. **Updated `sidekick/bootstrap.py`** — `build_decision_model()` now probes Bedrock in `auto` mode (falls through to Laya if no AWS creds), and `bedrock` choice is clean without the conditional BEDROCK_MODEL_ID hack.
6. **Updated `tests/test_provider_config.py`** — `SUPPORTED_PROVIDERS` assertion updated to include `bedrock`.
7. **Created `tests/test_bedrock_provider.py`** — Tests for missing creds, mock client, successful plan, and explicit selection.
8. **Updated `pyproject.toml` & packaging** — Added `aws = ["boto3>=1.34", "ask-sdk-core>=1.19", "ask-sdk-webservice-support>=1.3", "cryptography>=42.0"]` extra and verified clean editable installation.
9. **Implemented Alexa Security Verification** — Added `sidekick/api/alexa_verifier.py` implementing ASK request signature, cert URL, and timestamp validation with 13 tests.
10. **Created CI Quality Gate** — Added `.github/workflows/quality.yml` covering Python packaging, contract checks, test suites, frontend lint, typecheck, Vitest, build, and Playwright E2E.

### Verified Behavior Without Any Key
```
$ python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8000
→ Starts immediately, no errors, no key prompts
→ GET /healthz → 200 OK with model: laya or rule
→ POST /api/v1/requests (utterance: "write a note") → 200 OK, note written
→ coding.execute → reports NOT_CONFIGURED with precise per-provider hint
```

---

## 10. Implemented Features (Verified)

| Feature | Evidence | Status |
|---|---|---|
| Natural language request understanding | Laya NLP + rule fallback, 42-83% accuracy | ✅ DONE |
| Note write/read (real file I/O) | `tests/test_local_tools.py`, verify_backend 20/20 | ✅ DONE |
| Timer set/list (real in-memory) | `tests/test_local_tools.py` | ✅ DONE |
| Media open (URL launching) | `tests/test_local_tools.py` | ✅ DONE |
| Web search (browser delegation) | `tests/test_local_tools.py` | ✅ DONE |
| Reminder set | `tests/test_local_tools.py` | ✅ DONE |
| Safety policy + risk levels | `tests/test_safety.py` | ✅ DONE |
| Approval gates + plan_hash | `tests/test_engine.py` | ✅ DONE |
| Session management | `tests/test_sessions.py` | ✅ DONE |
| Decision engine fallback chain | `tests/test_engine.py` | ✅ DONE |
| AWS Bedrock decision model | `tests/test_bedrock_model.py` (mocked in CI) | ✅ DONE (live needs AWS creds) |
| AWS Bedrock coding provider | `tests/test_bedrock_provider.py` (mocked in CI) | ✅ DONE (live needs AWS creds) |
| Alexa Skills Kit adapter & security | `tests/test_alexa.py`, `tests/test_alexa_security.py` (13 tests) | ✅ DONE (live Echo needs Dev Console registration) |
| MCP stdio server | `tests/test_transports.py` | ✅ DONE |
| Coding execution service | `tests/test_coding_end_to_end.py` | ✅ DONE |
| Workspace safety + sandboxing | `tests/test_workspace_safety.py` | ✅ DONE |
| React/Vite/TS frontend | 162 unit tests passing, production build | ✅ DONE |
| Voice I/O (Web Speech API) | `tests/unit/speech.test.ts` | ✅ DONE |
| Movie Buddy companion | `tests/unit/movie-buddy.test.tsx` (11 tests) | ✅ DONE |
| Browser E2E Tests | `web/tests/e2e/app.spec.ts` (27 tests) | ✅ DONE (Playwright Chromium) |
| Client capability execution | `tests/unit/app.test.tsx`, verify_backend | ✅ DONE |
| SSE event streaming | `tests/test_streaming.py` | ✅ DONE |
| OpenAI-compatible HTTP coding provider | `tests/test_provider_config.py` | ✅ DONE |
| Local CLI coding provider | `tests/test_providers.py` | ✅ DONE |
| Contract compatibility | `scripts/check_contract_compat.py` & contract tests | ✅ DONE |

---

## 11. Partial, Blocked, and Unverified Features

| Feature | Status | Blocker |
|---|---|---|
| Live AWS Bedrock inference (decision) | UNVERIFIED LIVE | Needs `AWS_ACCESS_KEY_ID` / IAM role (mocked in tests) |
| Live AWS Bedrock coding | UNVERIFIED LIVE | Needs AWS credentials + `SIDEKICK_PROVIDER=bedrock` (mocked in tests) |
| Live Alexa Echo hardware invocation | UNVERIFIED LIVE | Needs Amazon Developer Console skill registration + `ALEXA_SKILL_ID` |
| Live remote LLM coding | UNVERIFIED LIVE | Needs `SIDEKICK_LLM_API_KEY` + compatible endpoint |
| Live local CLI coding (claude/cursor) | UNVERIFIED LIVE | Needs CLI installed + `SIDEKICK_CODING_CLI` |
| Movie Buddy commentary model | OPTIONAL | Heuristic local engine works; model endpoint is optional |
| Production Alexa deployment | REQUIRES CLOUD DEPLOY | Needs public HTTPS endpoint, Amazon Developer account, Echo hardware |

---

## 12. Hackathon Requirements (Evidence Summary)

| Req | Description | Status |
|---|---|---|
| R1 | Voice-first experience | ✅ Web Speech API + Alexa endpoint |
| R2 | Real execution, no fake success | ✅ Real file I/O, real diff, real test runner |
| R3 | Alexa track alignment | ✅ ASK request/response, skill ID validation |
| R4 | MCP integration | ✅ JSON-RPC 2.0 stdio server |
| R5 | AWS Builder (Bedrock) | ✅ implemented + tested; live needs AWS creds |
| R6 | Open source compliance | ✅ Apache-2.0, clean repo, reproducible builds |
| R7 | Movie Buddy contextual experience | ✅ Subtitle-grounded, speech-rate-budgeted |

---

## 13. API Reference

### Backend (FastAPI, default port 8000)
| Method | Path | Description |
|---|---|---|
| GET | `/healthz` | Health check with model info |
| GET | `/api/v1/capabilities` | Tool inventory (server + client) |
| POST | `/api/v1/requests` | Main request handler (intent + execution) |
| POST | `/api/v1/actions/{id}/complete` | Client reports execution result |
| POST | `/api/v1/alexa` | Alexa Skills Kit webhook |
| GET | `/api/v1/docs` | FastAPI OpenAPI docs |

### Request Body (POST /api/v1/requests)
```json
{
  "request_id": "unique-string",
  "session_id": "session-string",
  "utterance": "write a note that milk is out",
  "confirmation": null
}
```

### Alexa Request (POST /api/v1/alexa)
Standard Alexa Skills Kit JSON format. Returns compliant ASK response with SSML speech and Simple card.

---

## 14. Known Bugs Fixed in This Session

| Bug | Fix | File |
|---|---|---|
| Windows session TTL boundary (microsecond precision) | Changed `>` to `>=` | `sidekick/core/sessions.py:254` |
| Frontend `client` state missing from CapabilityBar | Added `client` to state enum | `web/src/components/CapabilityBar.tsx` |
| Frontend missing `completeAction` API method | Added method + endpoint | `web/src/lib/api/client.ts`, `endpoints.ts` |
| Coding provider only offered HTTP API without key | Added Bedrock provider (AWS-auth) | `sidekick_execution/providers/bedrock.py` |
| `select_provider("auto")` didn't try Bedrock first | Updated candidate list order | `sidekick_execution/service.py` |
| Error message only mentioned `SIDEKICK_LLM_API_KEY` | Updated to list all 3 provider options | `sidekick_execution/service.py` |
| Packaging `pyproject.toml` missing `aws` extra for `boto3` | Added `aws` extra with `boto3`, `ask-sdk-core`, `ask-sdk-webservice-support`, `cryptography` | `pyproject.toml`, `scripts/check_packaging.py` |
| Alexa endpoint lacked ASK signature and timestamp verification | Implemented ASK cryptographic verifier & regression tests | `sidekick/api/alexa_verifier.py`, `sidekick/api/app.py`, `tests/test_alexa_security.py` |
| Repository lacked unified GitHub Actions quality gate | Added comprehensive repository workflow | `.github/workflows/quality.yml` |

---

## 15. Outstanding Risks and Next Steps (Priority Order)

1. **Push remediation to `integrated-sidekick`** — Push latest remediation commits and monitor the `.github/workflows/quality.yml` GitHub Actions run.
2. **Open Pull Request from `integrated-sidekick` to `main`** — Record older PRs #1, #4, and #13 as superseded by `integrated-sidekick`.
3. **AWS credentials configuration** — Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` if live Bedrock inference or coding provider testing is desired.
4. **Alexa skill registration** — Register skill in Amazon Developer Console with `ALEXA_SKILL_ID` when deploying to production with public HTTPS endpoint.
5. **Laya CPU latency** — First inference on CPU takes ~25s. Pre-loading (`LAYA_PRELOAD=1`) or GPU acceleration would improve demo responsiveness.

---

## 16. Demo Setup

```powershell
# Terminal 1: Start backend
python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8000

# Browser: http://127.0.0.1:8000/
# Interface A: Voice companion with microphone
# Interface B: Control room with capability matrix
```

**Demo sequences that work without any keys:**
1. "Write a note saying the demo works" → saves to `sidekick_runtime/notes/note.txt`
2. "Set a timer for 5 minutes" → timer stored in memory
3. "Open Spotify" → Sidekick plans `media.open` with destination `spotify` (client executes)
4. "Order me a pizza" → Honest refusal: "I do not have a capability for that"

---

## 17. Decisions Left Unresolved

| Decision | Why Not Resolved |
|---|---|
| Which AWS account/region to use for Bedrock | Requires user-specific AWS setup |
| Whether to use Claude 3 Sonnet or Haiku for Bedrock | Cost/latency tradeoff; user decides |
| Alexa skill name and invocation phrase | Requires Amazon account |
| Whether to add streaming SSE to Alexa responses | Alexa protocol is synchronous; not applicable |
| HuggingFace symlink warning on Windows | Not a bug; laya still works; suppressing the warning is a config-only change |

---

## 18. Security Checklist

- [x] No `.env` file committed (gitignored)
- [x] `.env.example` contains only placeholder values
- [x] No AWS key IDs (AKIA...) in any tracked file
- [x] No `sk-` (OpenAI-style) keys in any tracked file
- [x] API key is never logged, printed, or returned in error responses (`secret_values()` masking)
- [x] `sidekick_runtime/` is gitignored (no runtime state committed)
- [x] No force-push performed
- [x] No credentials committed in this session
