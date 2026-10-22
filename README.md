# Sidekick

**Voice-first intelligent companion with real task execution, sandboxing, coding agent integration, Alexa connectivity, MCP hosting, and contextual Movie Buddy.**

Sidekick understands what you *mean*, not just what you said: it resolves the final destination before a conflicting action runs, handles mid-sentence corrections, keeps multiple conversations isolated, executes genuine tasks through a secure sandbox, and tells you the truth about what happened.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │              User Interfaces                 │
                      │  - Interface A: Conversational Voice View    │
                      │  - Interface B: Developer Control Room       │
                      │  - Alexa Voice Endpoint / MCP Client Host    │
                      └──────────────────────┬───────────────────────┘
                                             │ HTTP POST /api/v1/requests (or SSE)
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │            Sidekick Core (FastAPI)           │
                      │  - SessionStore (thread-safe, bounded TTL)   │
                      │  - DecisionEngine: Intent parsing & routing  │
                      │  - Decision Models:                          │
                      │     * LayaDecisionModel (self-hosted / LAYA) │
                      │     * RuleDecisionModel (deterministic anchor│
                      │     * BedrockDecisionModel (AWS Bedrock)     │
                      │  - SafetyPolicy: risk levels & approval gate │
                      │  - ToolRegistry: Catalog & capability specs  │
                      └──────────────┬───────────────────────────────┘
                                     │
         ┌───────────────────────────┴───────────────────────────────┐
         │                                                           │
         ▼ (Local Tools)                                             ▼ (Delegated Tools)
┌───────────────────────────────┐                  ┌──────────────────────────────────────────┐
│  Built-in Server Adapters     │                  │    Execution Service Adapter             │
│  - NoteWrite / NoteRead       │                  │    `sidekick.tools.execution`            │
│  - TimerSet / TimerList       │                  └────────────────────┬─────────────────────┘
│  - WebSearch / MediaOpen      │                                       │ HTTP / JSON-RPC stdio
└───────────────────────────────┘                                       ▼
         ▲                                         ┌──────────────────────────────────────────┐
         │ Reported outcome                        │    Sidekick Execution Service            │
         │ (POST /v1/actions/{id}/complete)        │    `sidekick_execution`                  │
┌────────┴──────────────────────┐                  │    - JobManager & Event Store            │
│  Client-Executed Capabilities │                  │    - Workspace & Path Traversal Sandbox  │
│  - movie.play                 │                  │    - ToolAdapters (coding, system, web)  │
│  - media.play                 │                  │    - Coding Providers:                   │
│  - game.start (Chess/2048/TTT)│                  │       * Remote HTTP API (OpenAI-compat)  │
└───────────────────────────────┘                  │       * Local Coding CLI (authorized)    │
                                                   │       * Simulated Provider (test only)   │
                                                   │    - MCP Server (`mcp_server.py`)        │
                                                   └──────────────────────────────────────────┘
```

---

## What Works Today (Verified Evidence)

| Capability / Feature | Status | Verification Evidence |
|---|---|---|
| **Voice Interface (Speech-to-Text & TTS)** | REAL | Web Speech API in `web/src/lib/voice/*`; 162 Vitest tests and 27 Playwright E2E tests pass. |
| **Alexa Skills Kit Integration** | VERIFIED CODE | `/api/v1/alexa` endpoint with ASK signature/cert verification, timestamp validation, and intent execution in `tests/test_alexa.py` & `tests/test_alexa_security.py` (live AWS skill deployment requires Amazon Developer Console config). |
| **Model Context Protocol (MCP) Server** | REAL | Stdio JSON-RPC 2.0 MCP server (`python -m sidekick_execution mcp`) verified in `tests/test_transports.py`. |
| **Amazon Bedrock Decision Adapter** | VERIFIED CODE | `BedrockDecisionModel` with Converse API, Claude/Titan, automated region fallback, and deterministic fallback in `tests/test_bedrock_model.py` (mocked in CI; live AWS calls require configured credentials). |
| **Self-Hosted ML Decision Model** | REAL | `convaiinnovations/laya` supported with timeout protection and lazy load in `tests/test_laya_integration.py`. |
| **Deterministic Intent Routing** | REAL | 35 intent tests in `tests/test_intent_routing.py` passing. |
| **Sandboxed Execution & Workspace Safety** | REAL | Path escape, shell injection blocked in `tests/test_workspace_safety.py`. |
| **Reviewable Git Diffs & Test Verification**| REAL | Real git diffs and test exit codes reported in `tests/test_coding_end_to_end.py`. |
| **Local Tools (Notes, Timers, Search)** | REAL | Notes created in workspace, timers scheduled asynchronously in `tests/test_tools.py`. |
| **Movie Buddy (Caption-Driven Commentary)** | REAL | Dialogue grounding, speech rate budgets, cooldowns verified in `web/tests/unit/movie-engine.test.ts`. |
| **Dual Interface (Conversational & Control Room)** | REAL | Full single page application built to `web/dist/` and served at root `/`. |

---

## Quickstart

### Prerequisites
- Python 3.10+
- Node.js 18+ (for building the browser frontend)

### 1. Backend Setup
```bash
# Install core dependencies
pip install -e ".[dev]"

# (Optional) Install Laya ML model & AWS Bedrock dependencies
pip install -e ".[dev,laya,aws]"
```

### 2. Frontend Setup & Build
```bash
cd web
npm install
npm run build
cd ..
```

### 3. Launch the Application
```bash
# Start FastAPI backend (automatically serves the built React client at /)
python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8000
```
Open **`http://127.0.0.1:8000`** in your browser.

---

## Running the Verification Suites
 
### Python Backend Suite (389 Tests: 382 passed, 7 skipped)
```bash
python -m pytest
```

### Packaging & Wheel Inspection
```bash
python scripts/check_packaging.py --build
```

### Contract Conformance Checks
```bash
python -m pytest tests/test_core_contract.py tests/test_contract_compat.py tests/test_execution_contract.py -v
```

### Web Frontend Suite (Typecheck, Lint, Vitest & Playwright E2E)
```bash
cd web
npm run verify
npm run test:e2e
```

---

## MCP Server (Model Context Protocol)
Run Sidekick's execution tools as a standard stdio MCP server:
```bash
python -m sidekick_execution mcp
```
Compatible with any MCP host (Claude Code, Cursor, Zed) for discovering and running real execution tools.

---

## Alexa Skills Kit Endpoint
Send Alexa requests directly to Sidekick:
```bash
curl -X POST http://127.0.0.1:8000/api/v1/alexa \
  -H "Content-Type: application/json" \
  -d '{
    "version": "1.0",
    "session": {"sessionId": "demo-session-1"},
    "request": {
      "type": "IntentRequest",
      "intent": {
        "name": "SidekickIntent",
        "slots": {"Utterance": {"value": "set a timer for 5 minutes"}}
      }
    }
  }'
```

---

## License
Apache-2.0. See `LICENSE` for details.
