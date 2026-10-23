# Sidekick

**Voice-first intelligent companion with real task execution, sandboxing, coding agent integration, Alexa connectivity, MCP hosting, voice-controlled gaming, and contextual Movie Buddy.**

Sidekick understands what you *mean*, not just what you said: it resolves intent before conflicting actions run, handles natural speech corrections, keeps sessions isolated, executes genuine tasks through a secure sandbox, enforces strict chess rules with voice commands, and provides truthful status reporting.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │              User Interfaces                 │
                      │  - Interface A: Conversational Voice Surface │
                      │  - Interface B: Developer Control Room       │
                      │  - Games View: Chess, Tic-Tac-Toe, 2048      │
                      │  - Movie Buddy: Contextual Companion Surface │
                      │  - Alexa Voice Endpoint / ASK Web Service    │
                      └──────────────────────┬───────────────────────┘
                                             │ HTTP POST /api/v1/requests (or SSE)
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │            Sidekick Core (FastAPI :8000)     │
                      │  - SessionStore: Isolated conversational turn │
                      │  - DecisionEngine: Intent parsing & routing  │
                      │  - Decision Models:                          │
                      │     * RuleDecisionModel (deterministic anchor│
                      │     * LayaDecisionModel (self-hosted / LAYA) │
                      │     * BedrockDecisionModel (Amazon Bedrock)  │
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
│  - WebSearch / MediaOpen      │                                       │ HTTP :8088 / MCP Stdio
└───────────────────────────────┘                                       ▼
         ▲                                         ┌──────────────────────────────────────────┐
         │ Reported outcome                        │    Sidekick Execution Service (:8088)    │
         │ (POST /v1/actions/{id}/complete)        │    `sidekick_execution`                  │
┌────────┴──────────────────────┐                  │    - JobManager & Event Store            │
│  Client-Executed Capabilities │                  │    - Workspace & Path Traversal Sandbox  │
│  - Movie Buddy (Caption LLM)  │                  │    - ToolAdapters (coding, system, web)  │
│  - Voice Chess (FIDE Rules)   │                  │    - Coding Providers:                   │
│  - Voice Tic-Tac-Toe (Minimax)│                  │       * Amazon Bedrock (Qwen / Claude)   │
│  - Voice 2048 (Merge Engine)  │                  │       * Remote HTTP API (OpenAI-compat)  │
└───────────────────────────────┘                  │       * Local Coding CLI (authorized)    │
                                                   │       * Simulated Provider (test only)   │
                                                   │    - Stdio MCP Server (`mcp_server.py`)  │
                                                   └──────────────────────────────────────────┘
```

---

## Features & Implementation Reality

| Capability / Component | Real Status | Verification & Implementation Evidence |
|---|---|---|
| **Movie Buddy** | VERIFIED LIVE | Dialogue-grounded commentary based on movie subtitle track; audio ducking (video drops to 20% volume while Sidekick speaks, restores to 100%); warm natural companion tone; Groq LLM integration (`openai/gpt-oss-120b`). Verified in `web/tests/unit/movie-buddy.test.tsx` and live browser. |
| **Chess Engine & Voice Commands** | VERIFIED LIVE | Full FIDE rules engine via `chess.js` (en passant, castling, promotion, check, checkmate, stalemate). Disambiguates candidate moves, rejects illegal moves with explanation, supports natural voice ("Move knight to F3", "Pawn in front of king two squares", "Castle kingside"). Sidekick AI plays legal response and announces moves. Verified in `web/tests/unit/chess-engine.test.ts`. |
| **Voice Gaming Suite** | VERIFIED LIVE | Playable via mouse, keyboard, and speech: Tic-Tac-Toe against minimax engine ("Play center", "Cell 5"), 2048 merge puzzle ("Swipe left", "Slide up"). Verified in `web/tests/unit/voice-games.test.ts`. |
| **Model Context Protocol (MCP)** | VERIFIED LIVE | Stdio JSON-RPC 2.0 MCP server (`python -m sidekick_execution mcp`) exposing `coding.execute`, `coding_plan`, `coding_apply`, `run_tests`, `git_diff` to compatible MCP hosts (Claude Code, Cursor). Verified in `tests/test_transports.py`. |
| **Alexa Skills Kit Endpoint** | VERIFIED LOCALLY | Full ASK HTTP web service at `/api/v1/alexa` with signature certificate verification, timestamp validation, application ID checking, and intent routing to DecisionEngine in `sidekick/api/alexa.py`. Verified in `tests/test_alexa.py` and `tests/test_alexa_security.py`. |
| **Amazon Bedrock Coding Provider** | PARTIAL / BLOCKED | Integration with AWS Bedrock via boto3 Converse API and `invoke_model`. Configured for model `qwen.qwen3-coder-30b-a3b-v1:0` in `eu-north-1` (and `anthropic.claude-3-sonnet-20240229-v1:0`). Live AWS inference status is honestly reported as **BLOCKED** pending AWS account verification approval. Verified in `tests/test_bedrock_provider.py`. |
| **Sandboxed Execution & Safety Gate** | VERIFIED LIVE | Path traversal prevention, shell injection boundaries, durable job records, and mandatory human approval gate for file modifications in `sidekick_execution/`. Verified in `tests/test_workspace_safety.py` and `tests/test_coding_end_to_end.py`. |
| **Conversational Surface & Control Room** | VERIFIED LIVE | Dual UI: Interface A (voice-first conversation) and Interface B (developer control room with live architecture state, request history, diff inspector, and approval controls). Built in React 18 and served at `/`. |

---

## Quickstart

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm

### 1. Backend Setup
```bash
# Clone and enter directory
git clone https://github.com/tanmay17-gif/Sidekick.git
cd Sidekick

# Install Python package in development mode
pip install -e ".[dev]"
```

### 2. Frontend Setup & Build
```bash
cd web
npm install
npm run build
cd ..
```

### 3. Launch Services

#### Option A: Run Full Application (Core API + Execution Service)
```bash
# Terminal 1: Start Execution Service on port 8088
python -m sidekick_execution serve --port 8088

# Terminal 2: Start Core API on port 8000
python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8000
```
Open **`http://127.0.0.1:8000`** in your browser.

#### Option B: Frontend Development Mode
```bash
cd web
npm run dev
```
Open **`http://localhost:5173`** with hot reloading.

---

## Model Context Protocol (MCP) Server

Sidekick's execution capabilities can be driven directly by any MCP client (such as Claude Code, Cursor, or Zed):
```bash
python -m sidekick_execution mcp
```
The server speaks JSON-RPC 2.0 over standard I/O (protocol version `2024-11-05`) and exposes:
- `coding_plan`: generates a structured file-edit plan
- `coding_apply`: applies changes inside the authorized workspace sandbox
- `run_tests`: runs unit test suites in the sandbox and captures exit codes
- `git_diff`: computes exact git diffs of uncommitted changes

---

## Alexa Integration

The Alexa endpoint is accessible at:
- `POST /api/v1/alexa`
- `POST /v1/alexa`

To test locally:
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
        "slots": {"Utterance": {"value": "ask Sidekick to fix the login page and run the tests"}}
      }
    }
  }'
```

In production, configure `ALEXA_SKILL_ID` and `ALEXA_VERIFY_SIGNATURE=true` to enforce cryptographic signature chain verification.

---

## Configuration & Environment Variables

Copy the example environment files:
```bash
cp .env.example .env
cp web/.env.example web/.env.local
```

### Key Configuration Variables:

| Variable | Description | Default / Example |
|---|---|---|
| `SIDEKICK_PROVIDER` | Coding provider for execution (`bedrock`, `http_api`, `simulated`) | `bedrock` |
| `BEDROCK_MODEL_ID` | Amazon Bedrock model ID | `qwen.qwen3-coder-30b-a3b-v1:0` |
| `AWS_REGION` | AWS Region for Bedrock inference | `eu-north-1` |
| `AWS_ACCESS_KEY_ID` | AWS Access Key (standard AWS credential chain) | *Configured securely* |
| `AWS_SECRET_ACCESS_KEY` | AWS Secret Key | *Configured securely* |
| `SIDEKICK_EXECUTION_URL` | URL of the execution service | `http://127.0.0.1:8088` |
| `ALEXA_SKILL_ID` | Authorized Alexa Skill ID | *Optional for testing* |
| `VITE_GROQ_API_KEY` | Groq API Key for Movie Buddy companion banter | *Optional for local LLM* |
| `VITE_GROQ_MODEL` | Groq model for Movie Buddy | `openai/gpt-oss-120b` |

---

## Automated Verification Suites

### 1. Python Backend Test Suite (395 Tests)
```bash
pytest -q
```
*Expected: 388 passed, 7 skipped, 0 failures.*

### 2. Frontend Vitest Suite (14 Test Files, 179 Tests)
```bash
cd web
npm test -- --run
```
*Expected: 14 passed (14), 179 passed (179).*

### 3. Frontend Type Check
```bash
cd web
npm run typecheck
```
*Expected: 0 errors.*

### 4. Production Build Verification
```bash
cd web
npm run build
```

---

## Deployment & Verification Checklist

- [x] **Movie Buddy**: Verified live in browser with subtitle-grounded reactions, speech rate budgeting, and audio ducking.
- [x] **Chess**: Full legal rules enforced via `chess.js`, disambiguation prompt, AI response, voice commands verified.
- [x] **Voice Games**: Tic-Tac-Toe minimax and 2048 directional swipes verified by unit tests and playable UI.
- [x] **MCP Server**: Stdio JSON-RPC 2.0 tested with `initialize`, `tools/list`, `tools/call`.
- [x] **Alexa ASK**: Security verifier and intent adapter tested for valid and invalid signatures.
- [x] **Bedrock Coding Provider**: SDK Converse API and model fallback tested; status correctly reports `BLOCKED` when AWS account verification is pending.
- [x] **Security**: No hardcoded API keys or secrets in source code; `.gitignore` validated.

---

## License
Apache-2.0. See `LICENSE` for details.
