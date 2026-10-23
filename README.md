<div align="center">

# 🎙️ Sidekick

**A voice-first agent layer that exposes real-world and developer actions to Alexa+ through a standards-compliant MCP server.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev)
[![MCP Protocol](https://img.shields.io/badge/MCP-2025--11--25-purple.svg)](https://modelcontextprotocol.io)
[![Transport](https://img.shields.io/badge/Transport-Streamable%20HTTP%20%26%20stdio-orange.svg)](https://modelcontextprotocol.io)

</div>

---

## 🏆 Hackathon Submission Details

* **Hackathon**: [Build, Ship, Shape: Amazon Developer Hackathon 2026](https://amazonappdev2026.devpost.com/)
* **Primary Track**: **Alexa+ Track** — Standards-compliant MCP tool server (spec version `2025-11-25`) served over **Streamable HTTP** (`/mcp`) and stdio, paired with an Agent Skill definition ([alexa_plus/SKILL.md](file:///c:/Users/Mrunal%20Amkar/OneDrive/Documents/Sidekick/alexa_plus/SKILL.md)) and an interactive web simulator.
* **AWS Builder Mini Challenge**: Direct integration with **Amazon Bedrock**:
  * `BedrockDecisionModel`: Intent classification and tool routing using Amazon Bedrock runtime API.
  * `BedrockCodingProvider`: Real AI code generation, file refactoring, and automated patch planning powered by **Qwen 3 Coder 30B** (`qwen.qwen3-coder-30b-a3b-v1:0`) and **Anthropic Claude 3.5 Sonnet** via `boto3`.
  * `AlexaRequestVerifier`: Cryptographic request signature verification, Amazon cert-chain inspection, and UTC timestamp tolerance.
* **Open Source Mini Challenge**: 100% open-source under the permissive [MIT License](LICENSE), zero proprietary locks, clean architecture, and 580+ automated tests across backend and frontend.
* **Significant Update Certification**: Detailed commit breakdown in [docs/HACKATHON_UPDATES.md](file:///c:/Users/Mrunal%20Amkar/OneDrive/Documents/Sidekick/docs/HACKATHON_UPDATES.md) proving 100% of the repository was built during the hackathon period (October 2026).

---

## ⚡ The Alexa+ Voice-to-Action Flow

Sidekick transforms Alexa+ into an autonomous desk co-pilot for engineers:

```
 ┌──────────────┐          ┌──────────────────────┐          ┌──────────────────────┐
 │ Developer    │  Voice   │ Alexa+               │  JSON-RPC│ Sidekick MCP Server  │
 │ Voice Query  ├─────────►│ Agentic LLM Engine   ├─────────►│ Streamable HTTP /mcp │
 └──────────────┘          └──────────────────────┘          └──────────┬───────────┘
                                                                        │
                                              ┌─────────────────────────┴─────────────┐
                                              ▼                                       ▼
                                     ┌──────────────────┐                   ┌──────────────────┐
                                     │ Safe Read Tools  │                   │ Approval Gate    │
                                     │ • coding.run_tests                   │ • coding.execute │
                                     │ • workspace.inspect                  │ • vcs.commit     │
                                     │ • vcs.diff                           │ (Human-in-loop)  │
                                     │ • system.info                        └──────────────────┘
                                     └──────────────────┘
```

1. **Voice Utterance**: You say, *"Alexa, run the project test suite and inspect what files changed."*
2. **Alexa+ Reasoning**: Alexa+'s agentic model evaluates the MCP tool catalog (`tools/list`), binds arguments, and invokes `coding.run_tests` and `vcs.diff`.
3. **Streamable HTTP Execution**: The request arrives over `POST /mcp` with standard JSON-RPC 2.0 payloads and session tracking (`Mcp-Session-Id`).
4. **Approval Gate**: High-risk actions (`coding.execute`, `vcs.commit`) halt and issue a confirmation token; Alexa+ prompts for verbal or visual approval before files are touched.
5. **Real Result**: Sidekick executes the real sandbox job and returns structured JSON output and a spoken summary.

---

## 🧰 MCP Tool Surface (Spec 2025-11-25)

Sidekick exposes 11 real execution capabilities. Every tool provides a human-readable `title`, `description`, `inputSchema`, `outputSchema`, and `annotations` matching MCP spec `2025-11-25`:

| Tool | Title | Description | Risk | Annotations (`readOnly`, `destructive`, `idempotent`) |
|---|---|---|---|---|
| `coding.execute` | Execute Code Changes | Real file edits via Bedrock / Claude / local AI | **High** | `readOnly: false`, `destructive: true`, `idempotent: false` |
| `coding.run_tests` | Run Project Test Suite | Run pytest/vitest in sandbox, return exit status | **Low** | `readOnly: true`, `destructive: false`, `idempotent: true` |
| `workspace.inspect` | Inspect Workspace Directory | Read directory layout, git branch, and file trees | **Low** | `readOnly: true`, `destructive: false`, `idempotent: true` |
| `vcs.diff` | Git Diff Workspace | Generate real `git diff` of the authorized workspace | **Low** | `readOnly: true`, `destructive: false`, `idempotent: true` |
| `vcs.commit` | Create Git Commit | Commit staged files with an approved message | **Medium** | `readOnly: false`, `destructive: false`, `idempotent: false` |
| `system.info` | System Runtime Info | Report OS, platform, CPU cores, memory telemetry | **Low** | `readOnly: true`, `destructive: false`, `idempotent: true` |
| `system.volume` | Control System Volume | Read or adjust master host system audio volume | **Medium** | `readOnly: false`, `destructive: false`, `idempotent: true` |
| `system.media_control` | Media Playback Control | Send multimedia keys (play, pause, next, mute) | **Low** | `readOnly: false`, `destructive: false`, `idempotent: false` |
| `system.open` | Open File or URL | Open files or URLs with host default handler | **Medium** | `readOnly: false`, `destructive: false`, `idempotent: true` |
| `system.clipboard` | System Clipboard Access | Read or write the system clipboard | **Medium** | `readOnly: false`, `destructive: false`, `idempotent: true` |
| `web.fetch` | Fetch Web Resource | Fetch web documentation or URLs via HTTP(S) | **Low** | `readOnly: true`, `destructive: false`, `idempotent: true` |

---

## ⚡ Test It in 2 Minutes

### Path A — Official MCP Inspector (Streamable HTTP)
Run the official Model Context Protocol Inspector against Sidekick:
```bash
# 1. Start the Sidekick execution service (which serves /mcp on port 8088)
python -m sidekick_execution serve --port 8088

# 2. Launch MCP Inspector (in another terminal)
npx @modelcontextprotocol/inspector http://127.0.0.1:8088/mcp
```
* The inspector connects over Streamable HTTP, performs the `initialize` handshake (spec `2025-11-25`), and lists all 11 tools with their schemas and annotations.

### Path B — Web-Based Alexa+ Simulator
```bash
# Start backend and frontend
python -m uvicorn sidekick.api.app:create_app --factory --port 8000
cd web && npm run dev
```
Open **[http://localhost:5173](http://localhost:5173)** and click the **"Alexa+ Simulator"** tab in the top navigation:
* Click quick-action buttons (*"Run project tests"*, *"Inspect workspace"*, *"Check git diff"*).
* Watch the live agentic step trace: Voice input → Intent match → `POST /mcp` JSON-RPC call → Structured response → Synthesized audio response.

---

## 🚀 5-Step Quick Start (From Fresh Clone)

### 1. Clone the repository
```bash
git clone https://github.com/tanmay17-gif/Sidekick.git
cd Sidekick
```

### 2. Install dependencies
```bash
# Python backend with AWS extras
pip install -e ".[aws,dev]"

# Web frontend
cd web && npm install && cd ..
```

### 3. Configure environment
```bash
cp .env.example .env
# Optional: add your AWS credentials for Amazon Bedrock in .env
# AWS_ACCESS_KEY_ID=your-key
# AWS_SECRET_ACCESS_KEY=your-secret
# AWS_REGION=us-east-1
# BEDROCK_MODEL_ID=qwen.qwen3-coder-30b-a3b-v1:0
```

### 4. Run tests to verify
```bash
# Backend pytest suite (390+ tests)
pytest

# Frontend vitest suite (179 tests)
cd web && npx vitest run && npx tsc --noEmit && cd ..
```

### 5. Launch the application
```bash
# Terminal 1: Core Brain + Web API (port 8000)
python -m uvicorn sidekick.api.app:create_app --factory --port 8000 --reload

# Terminal 2: Execution Service + MCP Streamable HTTP (port 8088)
python -m sidekick_execution serve --port 8088

# Terminal 3: Web UI (port 5173)
cd web && npm run dev
```

---

## 🔗 Connecting Other MCP Hosts

### Streamable HTTP (Remote / Network MCP Hosts)
Point any Streamable HTTP client to:
```
http://127.0.0.1:8088/mcp
```
Or run the dedicated MCP HTTP daemon on port 8089:
```bash
python -m sidekick_execution mcp-http --port 8089
```

### Claude Desktop (stdio)
Add to your `claude_desktop_config.json`:
```json
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

### Cursor / Windsurf
Add `python -m sidekick_execution mcp` in your editor's MCP server configuration.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Voice & Client Surface                        │
│   Alexa+ Agent Skill          Alexa+ Simulator        Developer UI      │
│   (alexa_plus/SKILL.md)      (web/src/components)    (Control Room)     │
└────────────────────┬──────────────────┬────────────────────────┬────────┘
                     │                  │                        │
                     ▼                  ▼                        │
          ┌───────────────────────────────────┐                  │
          │   Streamable HTTP /mcp Endpoint   │                  │
          │      MCP Protocol 2025-11-25      │                  │
          └─────────────────┬─────────────────┘                  │
                            │                                    │
┌───────────────────────────▼────────────────────────────────────▼─────────┐
│                     Sidekick Core & Execution Engine                    │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                      11 Registered Tools                        │   │
│   │   coding.*  │  vcs.*  │  workspace.*  │  system.*  │  web.fetch │   │
│   └────────────────────────────────┬────────────────────────────────┘   │
│                                    │                                    │
│   ┌────────────────────────────────┴────────────────────────────────┐   │
│   │                     Human-in-the-Loop Safety                    │   │
│   │           Cryptographic confirmation token approval gate        │   │
│   └────────────────────────────────┬────────────────────────────────┘   │
│                                    │                                    │
│   ┌────────────────────────────────┴────────────────────────────────┐   │
│   │                      Amazon Bedrock Runtime                     │   │
│   │          Qwen 3 Coder 30B  /  Claude 3.5 Sonnet (boto3)         │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 🎬 More Demos & Companion Apps

While the core focus of Sidekick is voice-first developer acceleration, Sidekick also bundles companion micro-apps for developer downtime:

* **Movie Buddy**: Adaptive film companion that tracks the playback clock, parses real subtitles, and answers contextual questions (*"What just happened?"*, *"Who was that?"*) without spoiling future plot points.
* **Voice Gaming Suite**: Hands-free voice chess powered by a full FIDE rules engine (`chess.js`), minimax AI opponent, and illegal-move verbal explanations, plus voice-controlled 2048 and Tic-Tac-Toe.
* **Local System Control**: Hands-free media playback, master volume adjustments, and system clipboard inspection.

---

## 🔐 Security & Safety Guarantee

| Layer | Policy |
|---|---|
| **Human-in-the-Loop** | High-risk tools (`coding.execute`, `vcs.commit`) require explicit confirmation tokens before touching the filesystem. |
| **Workspace Sandboxing** | Tools are strictly bounded to authorized directories; path traversal outside approved roots is blocked. |
| **Zero Secrets Policy** | Real credentials are loaded from local `.env` only. Zero keys exist in source code or git history. |
| **Alexa ASK Compliance** | Full RSA signature verification and timestamp validation on incoming ASK webhooks. |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
