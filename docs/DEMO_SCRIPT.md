# Sidekick Hackathon Demonstration Walkthrough & Video Script

**Target Duration:** 3 Minutes  
**Demonstrator:** Hackathon Presenter  
**Audience:** Judges (Amazon App Dev 2026, Alexa & AWS Tracks)  
**Target URL:** `http://127.0.0.1:8000/` (Integrated FastAPI + React bundle)

---

## Pre-Demo Setup Checklist (30 seconds before recording)
1. Ensure repository root is clean:
   ```bash
   python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8000
   ```
2. Open browser to `http://127.0.0.1:8000/`. The dual interface loads with Interface A (Conversational Voice Companion) active and Interface B (Control Room) available in the top bar.
3. Verify microphone permissions are granted in the browser.

---

## 3-Minute Demonstration Script

### Segment 1: The Problem & The Voice Experience (0:00 - 0:45)
**Visual:** Full screen showing Sidekick Interface A, glowing audio orb, and clean modern aesthetic.
**Speaker:**
> *"Voice assistants today suffer from two extremes: either they're generic chatbots that hallucinate without taking real action, or they just pop open Google search pages. Meet Sidekick: a voice-first intelligent assistant that performs genuine tasks with real sandboxed execution, Alexa and MCP connectivity, and contextual companion capabilities."*

**Action:** Click the microphone button (or speak):
> *"Write a note saying: Hackathon submission verified and ready for review."*

**Visual:**
- Orb pulses into listening state.
- Utterance appears in real time.
- State chip transitions: `getting ready` → `working` → `done`.
- Audio synthesizes: *"Saving your note."*
- Card displays the saved file path in `sidekick_runtime/notes/`.
- Presenter shows the actual `.txt` file created on the local file system.

---

### Segment 2: Safety Gates & Real Coding Agent Integration (0:45 - 1:30)
**Visual:** Switch to **Interface B: Control Room**. Show the capability matrix and live event stream.
**Speaker:**
> *"When actions modify code or affect the system, Sidekick never executes blindly. It enforces transparent safety policies with cryptographic plan hashes and explicit approvals."*

**Action:** Type or speak:
> *"Fix the failing tests in my python project."*

**Visual:**
- Decision Engine identifies `coding.execute`.
- Risk level is flagged as `HIGH`.
- UI presents an explicit approval modal showing the plan hash and affected workspace.
- Presenter clicks **"Approve Execution"**.
- Live event stream updates via SSE: sandbox initialized, tests run, git diff computed.
- The UI renders the real, reviewable Git diff and test result exit codes without faking success.

---

### Segment 3: Alexa Track & Model Context Protocol (MCP) (1:30 - 2:15)
**Visual:** Terminal split screen showing MCP and Alexa integration.
**Speaker:**
> *"Sidekick is built for the modern AI ecosystem. It connects natively to Alexa and serves as a Model Context Protocol (MCP) host."*

**Action:**
1. Present the Alexa Skills Kit integration:
   ```bash
   curl -X POST http://127.0.0.1:8000/api/v1/alexa \
     -H "Content-Type: application/json" \
     -d '{"version":"1.0","request":{"type":"IntentRequest","intent":{"name":"SidekickIntent","slots":{"Utterance":{"value":"set a timer for 5 minutes"}}}}}'
   ```
   Show compliant ASK response with PlainText speech and Alexa Card.
2. Demonstrate MCP Tool Discovery:
   ```bash
   python -m sidekick_execution mcp
   # Sends {"jsonrpc":"2.0","id":1,"method":"tools/list"} -> returns tools list with schemas
   ```
> *"Any MCP client—like Claude Code or Cursor—can discover and invoke Sidekick's real execution capabilities over standard JSON-RPC."*

---

### Segment 4: Contextual Movie Buddy (2:15 - 2:45)
**Visual:** Switch to **Movie Buddy** tab in the browser. Select the bundled film *Duck and Cover*.
**Speaker:**
> *"Finally, Sidekick includes Movie Buddy: an intelligent entertainment companion. Rather than interrupting with generic chatbot banter, Movie Buddy parses caption cues in real time, applies dialogue grounding, and respects strict speech rate budgets."*

**Action:**
- Press play on the video.
- As the narration begins, Movie Buddy displays real-time caption-grounded observations.
- Demonstrate that pausing the video pauses commentary; seeking respects cooldowns; and dialogue facts are strictly distinguished from interpretations.

---

### Segment 5: Conclusion & Hackathon Wrap-up (2:45 - 3:00)
**Visual:** Architecture diagram in Interface B, showing the clean decoupling of Core Brain, Execution Sandbox, and Voice Frontend.
**Speaker:**
> *"Sidekick delivers what assistants should have been all along: truthful execution, robust safety, universal connectivity through Alexa and MCP, and delightful contextual experiences. The entire repository is open source under Apache-2.0 and ready to test today. Thank you!"*
