---
name: sidekick-developer-skill
description: "Voice-first developer agent layer for Alexa+. Enables hands-free code modifications, testing, workspace inspection, and git operations through standard MCP 2025-11-25 over Streamable HTTP."
version: "1.0.0"
author: "Sidekick Team"
runtime:
  type: "mcp-agent"
  mcp_spec: "2025-11-25"
  transport: "streamable-http"
  endpoint: "/mcp"
---

# 🎙️ Sidekick — Alexa+ Agent Skill

Sidekick equips Alexa+ with a real developer execution co-pilot. When a developer asks Alexa+ to run tests, inspect their repository, check git diffs, or execute coding tasks, Alexa+ calls Sidekick's Model Context Protocol (MCP) server over **Streamable HTTP**.

## Architecture Overview

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

## Natural Voice Invocations

Alexa+ automatically maps natural developer language to Sidekick MCP tools:

| Natural Voice Request | Triggered MCP Tool | Action Taken |
|---|---|---|
| *"Alexa, run the test suite for this project"* | `coding.run_tests` | Executes pytest / vitest in sandbox; returns exit code and failures |
| *"Alexa, what files changed since last commit?"* | `vcs.diff` | Performs `git diff` and summarizes modified files and lines |
| *"Alexa, inspect my current repository"* | `workspace.inspect` | Lists directory layout, git status, and active branch |
| *"Alexa, fix the import bug in app.py"* | `coding.execute` | Plans and presents diff with confirmation token; awaits human approval |
| *"Alexa, commit these changes with message 'fix: imports'"* | `vcs.commit` | Creates real git commit upon approval |
| *"Alexa, what is the memory and CPU status?"* | `system.info` | Reads real host runtime capabilities and telemetry |
| *"Alexa, set the system volume to 50"* | `system.volume` | Adjusts host OS audio volume directly |

## Human-in-the-Loop Safety Policy

Per Amazon's Responsible AI guidelines:
1. **Low-risk tools** (`coding.run_tests`, `workspace.inspect`, `vcs.diff`, `system.info`, `web.fetch`) execute immediately without friction.
2. **High-risk tools** (`coding.execute`, `vcs.commit`, destructive edits) return `approval_required: true` along with a cryptographic confirmation token. Alexa+ prompts the user for verbal or visual confirmation before the change is committed to disk.

## Transports & Compatibility

* **Streamable HTTP (Primary)**: `POST /mcp` with protocol version `2025-11-25`. Supports session persistence via `Mcp-Session-Id` header.
* **Legacy Custom Skill Endpoint (Fallback)**: `POST /api/v1/alexa/ask` for classic Echo devices without MCP runtime support.
