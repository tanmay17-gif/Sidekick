<div align="center">

# 🎙️ Sidekick

**A voice-first AI companion that connects Alexa, your browser, and real coding agents — through a single MCP server.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev)
[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05-purple.svg)](https://modelcontextprotocol.io)

</div>

---

## What is Sidekick?

Sidekick is an open-source AI assistant platform with three integrated layers:

| Layer | What it does |
|---|---|
| 🗣️ **Alexa Skill** | Accepts voice commands, routes them through the brain |
| 🧠 **Core Brain** | Python API that decides what to do and calls execution tools |
| ⚙️ **Execution Service** | Real file editing, Git, testing, system control — exposed over MCP and HTTP |
| 🎬 **Web Client** | React browser UI with Movie Buddy, voice chess, 2048, and Tic-Tac-Toe |

---

## ✨ Features

### 🔗 MCP Server (Model Context Protocol)
The heart of Sidekick is its **fully standard MCP server** (protocol version `2024-11-05`, JSON-RPC 2.0 over stdio). Any MCP-compatible host can connect and use these tools:

| Tool | Description | Risk |
|---|---|---|
| `coding.execute` | Real file edits via AI (Bedrock / Claude / Codex) | High |
| `coding.run_tests` | Run any project's test suite, return real exit status | Low |
| `workspace.inspect` | Inspect authorized workspace — files, structure, git state | Low |
| `vcs.diff` | Real `git diff` of an authorized workspace | Low |
| `vcs.commit` | Create a real Git commit with a message | Medium |
| `system.info` | Report real runtime capabilities of the host machine | Low |
| `system.volume` | Read or set master system volume (0–100) | Medium |
| `system.media_control` | Send multimedia key presses (play, pause, next, stop, mute, etc.) | Low |
| `system.open` | Open files or URLs with the OS default handler | Medium |
| `system.clipboard` | Read or write the real system clipboard | Medium |
| `web.fetch` | Make real HTTP(S) requests and return the server response | Low |

**Connecting Claude Desktop:**
```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "sidekick": {
      "command": "python",
      "args": ["-m", "sidekick_execution", "mcp"],
      "cwd": "/path/to/Sidekick"
    }
  }
}
```

**Connecting Cursor:**
Add the same config to Cursor → Settings → MCP Servers.

---

### 🤖 Coding Agent Integrations

Sidekick supports three coding backends — pick whichever fits:

#### Option A — AWS Bedrock (Qwen 3 Coder / Claude)
```env
SIDEKICK_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=your-key
AWS_SECRET_ACCESS_KEY=your-secret
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=qwen.qwen3-coder-30b-a3b-v1:0
```

#### Option B — Claude API / OpenAI Codex (HTTP API)
```env
SIDEKICK_PROVIDER=http_api
SIDEKICK_LLM_API_KEY=sk-ant-...          # or sk-... for OpenAI
SIDEKICK_LLM_BASE_URL=https://api.anthropic.com/v1
SIDEKICK_LLM_MODEL=claude-3-5-sonnet-20241022
```

#### Option C — Cursor / Claude CLI / Aider (local binary)
```env
SIDEKICK_PROVIDER=local_cli
SIDEKICK_CODING_CLI=claude          # or: aider, cursor
SIDEKICK_CODING_CLI_ARGS=["--json-plan","--task","{task}","--workspace","{workspace}"]
```

> Install the Claude CLI: `npm install -g @anthropic-ai/claude-code`

---

### 🗣️ Alexa Voice Integration

Sidekick exposes an Alexa Smart Home + Custom Skill HTTP endpoint:

```
POST /api/v1/alexa/ask
```

Supports intents:
- `PlayMovie` / `StopMovie` / `PauseMovie`
- `SearchFlight` / `BookFlight`
- `PlayChess` / `PlayTicTacToe` / `Play2048`
- `RunCode` / `CommitChanges` / `RunTests`
- `SetVolume` / `GetVolume` / `MediaControl`
- `OpenFile` / `FetchUrl` / `ClipboardRead` / `ClipboardWrite`
- `GetCapabilities` / `Help`

**Configure your Alexa Skill endpoint** to:
```
https://your-domain.com/api/v1/alexa/ask
```

---

### 🎬 Movie Buddy

An AI-powered movie companion that watches films alongside you:

- **Voice-activated** — say "Hey Sidekick, what just happened?" during a movie
- **Subtitle-grounded** — commentary is always based on actual caption lines, never hallucinated
- **Natural personality** — warm, witty, cozy tone. Reacts like a friend on the couch
- **Auto audio ducking** — video drops to 20% volume while Sidekick speaks
- **Groq / OpenAI compatible** — configure any OpenAI-compatible endpoint

```env
# web/.env.local
VITE_GROQ_API_KEY=your-groq-key
VITE_GROQ_MODEL=openai/gpt-oss-120b
VITE_GROQ_API_ENDPOINT=https://api.groq.com/openai/v1/chat/completions
```

---

### 🎮 Voice Gaming Suite

Play games entirely by voice:

| Game | Voice Commands |
|---|---|
| **Chess** | "Move pawn to e4", "Castle kingside", "What are my options?" |
| **Tic-Tac-Toe** | "Play top left", "Play center", "Restart" |
| **2048** | "Swipe left", "Move right", "Start new game" |

The chess engine uses the full `chess.js` FIDE rules engine — checkmate, castling, promotion, illegal-move explanations, and minimax AI opponent.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Voice & UI Layer                         │
│   Alexa Skill (ASK)          Browser (React/Vite port 5173)     │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP POST /api/v1/*
┌──────────────────────▼──────────────────────────────────────────┐
│               Core Brain  (FastAPI  port 8000)                  │
│   Intent routing · Decision model · Laya · Rule engine          │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP POST /v1/actions
┌──────────────────────▼──────────────────────────────────────────┐
│           Execution Service  (stdlib HTTP  port 8088)           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                      Tool Registry                       │   │
│  │  coding.execute · vcs.diff · vcs.commit · system.* · ..  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────┐    ┌────────────────────────────────┐     │
│  │   MCP Server     │    │      Coding Provider           │     │
│  │  stdio/JSON-RPC  │    │  Bedrock │ HTTP API │ LocalCLI │     │
│  │  2024-11-05      │    └────────────────────────────────┘     │
│  └──────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │ MCP stdio (JSON-RPC)
┌────────┴────────────────────────────────────────────────────────┐
│              MCP Host Clients (optional)                        │
│     Claude Desktop · Cursor · Windsurf · Any MCP host           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- Git

### 1. Clone & Install

```bash
git clone https://github.com/tanmay17-gif/Sidekick.git
cd Sidekick

# Backend
pip install -e ".[dev]"

# Frontend
cd web && npm install && cd ..
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your credentials (AWS, Alexa Skill ID, etc.)

cp web/.env.example web/.env.local
# Edit web/.env.local with your Groq key for Movie Buddy
```

### 3. Run

```bash
# Terminal 1 — Core Brain
python -m uvicorn sidekick.api.app:create_app --factory --port 8000 --reload

# Terminal 2 — Execution Service (with MCP)
python -m sidekick_execution serve --port 8088

# Terminal 3 — Web UI
cd web && npm run dev
```

Open: [http://localhost:5173](http://localhost:5173)

### 4. MCP only (for Claude Desktop / Cursor)

```bash
python -m sidekick_execution mcp
```

---

## 🔐 Security & Secrets

| File | Status | Contains |
|---|---|---|
| `.env` | ✅ gitignored | AWS keys, Alexa Skill ID |
| `web/.env.local` | ✅ gitignored | Groq API key |
| `.env.example` | ✅ tracked | **Placeholders only** |
| `web/.env.example` | ✅ tracked | **Placeholders only** |
| Source code | ✅ clean | Zero hardcoded credentials |

**No API keys or secrets are ever committed to this repository.**

---

## 🧪 Testing

```bash
# Backend (395 tests)
pytest

# Frontend (179 tests)
cd web && npx vitest run

# Type check
cd web && npx tsc --noEmit
```

---

## 📁 Project Structure

```
Sidekick/
├── sidekick/                  # Core brain — FastAPI, intent routing, Alexa
│   ├── api/                   # REST endpoints + Alexa ASK handler
│   ├── brain/                 # Decision engine, Laya model
│   └── tools/                 # Tool definitions for the brain
├── sidekick_execution/        # Execution service — MCP, HTTP, tools
│   ├── providers/             # Bedrock, HTTP API, Local CLI, Simulated
│   ├── adapters/              # Coding, system, web, VCS adapters
│   ├── mcp_server.py          # MCP stdio server (JSON-RPC 2024-11-05)
│   └── http_service.py        # HTTP + SSE transport
├── web/                       # React browser client
│   └── src/
│       ├── components/        # UI: Chess, TicTacToe, 2048, MovieBuddy
│       └── lib/               # Game engines, movie provider, voice utils
├── tests/                     # Backend pytest suite
├── docs/                      # Public documentation
│   ├── core-integration.md    # Brain ↔ Execution contract
│   ├── execution-service-contract.md
│   └── DEMO_SCRIPT.md
├── .env.example               # Root env template (no real values)
├── LICENSE                    # MIT
└── README.md
```

---

## 📡 API Reference

### Execution Service HTTP API

```
GET  /v1/health              Liveness + runtime summary
GET  /v1/capabilities        Full capability report (all tools + provider status)
POST /v1/actions             Submit an action (coding, git, system, etc.)
GET  /v1/actions             List actions
GET  /v1/actions/{id}        Get one action
POST /v1/actions/{id}/approve  Approve a pending high-risk action
POST /v1/actions/{id}/cancel   Cancel an action
GET  /v1/actions/{id}/events   SSE stream of live job events
```

### Core Brain API

```
POST /api/v1/alexa/ask       Alexa ASK request handler
POST /api/v1/requests        Natural language request interpreter
GET  /api/v1/capabilities    Aggregated capability report
GET  /api/v1/media/catalog   Movie/media catalog
GET  /api/v1/actions/{id}    Action status
```

---

## 🔌 Connecting External Coding Agents

### Alexa → Bedrock (Qwen 3 Coder)
Voice command → Alexa → Sidekick Brain → Execution Service → AWS Bedrock → real file edits

### Alexa → Claude API
```env
SIDEKICK_PROVIDER=http_api
SIDEKICK_LLM_BASE_URL=https://api.anthropic.com/v1
SIDEKICK_LLM_API_KEY=sk-ant-...
SIDEKICK_LLM_MODEL=claude-3-5-sonnet-20241022
```

### Claude Desktop / Cursor → Sidekick MCP
MCP host spawns `python -m sidekick_execution mcp` and calls any of the 11 tools.

### Alexa → Claude CLI (local)
```env
SIDEKICK_PROVIDER=local_cli
SIDEKICK_CODING_CLI=claude
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Commit your changes: `git commit -m "feat: add my feature"`
4. Push and open a PR against `main`

Please keep `.env` and `web/.env.local` out of commits. Real secrets must never appear in the repository.

---

## 📄 License

[MIT](LICENSE) — free to use, modify, and distribute.

---

<div align="center">
Made with ❤️ by the Sidekick Contributors
</div>
