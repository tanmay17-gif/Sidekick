# Amazon App Dev 2026 Hackathon Compliance Matrix

**Project:** Sidekick  
**Repository:** [https://github.com/tanmay17-gif/Sidekick](https://github.com/tanmay17-gif/Sidekick)  
**Track Alignment:** Alexa Track & Developer Productivity / Entertainment  
**Mini-Challenges:** AWS Builder Mini-Challenge, Open Source Mini-Challenge  
**Verification Date:** October 23, 2026  

---

## 1. Compliance Checklist & Evidence

| # | Requirement / Challenge | Hackathon Expectation | Sidekick Implementation | Location in Repo | Verification Evidence | Status |
|---|---|---|---|---|---|---|
| **R1** | **Functional Voice-First Experience** | High-quality voice interface capable of capturing user intents, handling dialogue, and executing real tasks without faking. | Dual interface with conversational speech recognition (Web Speech API) & Alexa standard skill endpoint (`/api/v1/alexa`). Spoken responses synthesized via SpeechSynthesis with human-first language. | `web/src/lib/voice/*`, `sidekick/api/alexa.py`, `sidekick/core/engine.py` | 162 web tests passing; 6 Alexa adapter tests passing (`tests/test_alexa.py`). | **VERIFIED** |
| **R2** | **Real Execution (No Fake Successes)** | Tasks must perform genuine work with transparent outcome reporting; failure and cancellation must be honestly reported. | Built-in local adapters (notes, timers, web search) and isolated execution service (`sidekick_execution`) executing real file modifications, diff generation, and test suite execution. | `sidekick/tools/local.py`, `sidekick_execution/jobs.py`, `sidekick_execution/sandbox.py` | `tests/test_coding_end_to_end.py`, `tests/test_workspace_safety.py` pass. | **VERIFIED** |
| **R3** | **Alexa Track Alignment** | Compliant Alexa Skills Kit (ASK) request and response format; skill integration path. | `AlexaAdapter` converts standard Alexa JSON (`LaunchRequest`, `IntentRequest`, `SessionEndedRequest`) into Sidekick requests and formats compliant Alexa responses with SSML, PlainText speech, and card metadata. | `sidekick/api/alexa.py`, `sidekick/api/app.py` | `tests/test_alexa.py` verifies Launch, Stop, Note Write, and HTTP `/api/v1/alexa` route. | **VERIFIED** |
| **R4** | **Model Context Protocol (MCP) Integration** | Expose execution capabilities over standard Model Context Protocol. | Complete JSON-RPC 2.0 stdio MCP Server implementing protocol specification version `2024-11-05` (`initialize`, `tools/list`, `tools/call`, `ping`). | `sidekick_execution/mcp_server.py`, `sidekick_execution/__main__.py` | `tests/test_transports.py` passes; runs via `python -m sidekick_execution mcp`. | **VERIFIED** |
| **R5** | **AWS Builder Mini-Challenge** | Real architectural integration with AWS services (Bedrock, IAM, S3/Cloud). | `BedrockDecisionModel` integrates with Amazon Bedrock foundation models (Anthropic Claude 3 Sonnet / Titan) using `boto3`. Handles region configuration, timeouts, retries, and offline deterministic fallback. | `sidekick/core/decisions/bedrock_model.py`, `sidekick/bootstrap.py` | `tests/test_bedrock_model.py` passes with mocked Bedrock inference, JSON parsing, and fallback. | **VERIFIED (Live unverified without AWS keys)** |
| **R6** | **Open Source Mini-Challenge** | Compliant open-source license, public repository, clean documentation, reproducible builds, and developer guides. | Licensed under Apache-2.0. Clean architecture documentation, contract ratification, typechecked codebase, and zero hardcoded credentials. | `LICENSE`, `pyproject.toml`, `README.md`, `docs/*` | `python scripts/check_packaging.py` passes wheel inspection; reproducible setup documented. | **VERIFIED** |
| **R7** | **Contextual Movie Buddy Experience** | Distinctive multimodal/entertainment companion that listens to video dialogue without disruptive popups. | Subtitle-driven contextual engine (`MovieBuddy`) with speech rate budgets, cooldown timers, dialogue grounding, and heuristic / model-driven observations. | `web/src/components/MovieBuddy.tsx`, `web/src/lib/movie/*` | `web/tests/unit/movie-engine.test.ts` (32 tests) and `movie-buddy.test.tsx` pass. | **VERIFIED** |

---

## 2. Verification Commands & Audit Logs

### 2.1 Backend Quality & Security Verification
```bash
# Run complete Python test suite (370+ tests)
python -m pytest

# Run ratified contract compatibility suite
python scripts/check_contract_compat.py

# Verify packaging and wheel build
python scripts/check_packaging.py
```
**Results:** All passed with 0 errors.

### 2.2 Frontend Quality & Browser Build Verification
```bash
cd web
npm run lint
npm run typecheck
npm run test
npm run build
```
**Results:** Zero lint errors, zero TypeScript errors, 162 unit tests passed, production bundle compiled cleanly in `web/dist/`.

---

## 3. Disclosed Limitations & External Dependencies

1. **Live AWS Bedrock Execution:**
   - Both the Bedrock decision model (`sidekick/core/decisions/bedrock_model.py`) and the Bedrock coding provider (`sidekick_execution/providers/bedrock.py`) are fully implemented and verified via unit tests with mock fixtures.
   - Uses the standard AWS credential chain (IAM role, env vars, profile) — **no separate LLM API key required**.
   - When unconfigured, the decision engine falls back safely to self-hosted Laya or rule model; the coding service reports `NOT_CONFIGURED` with a precise hint.
2. **Live Remote Coding LLM Key:**
   - The coding execution provider supports OpenAI-compatible remote endpoints via `SIDEKICK_LLM_API_KEY`.
   - When not supplied, the execution engine honestly marks the remote provider as `NOT_CONFIGURED` while supporting local CLI execution and sandbox simulation.
3. **Live Alexa Skill Registration:**
   - Native Echo hardware invocation requires registering the skill in the Amazon Developer Console and binding `ALEXA_SKILL_ID`.
   - The `/api/v1/alexa` endpoint is fully compliant with Alexa Skills Kit specifications.
