# Sidekick

**Voice-first intelligent companion.** Sidekick understands what you *mean*,
not just what you said: it resolves the final destination before a conflicting
action runs, handles mid-sentence corrections, keeps several conversations
apart, and tells you the truth about what happened.

This repository currently contains the **core brain** (Agent 1): intent
resolution, safety policy, session orchestration and the stable HTTP contract
that the execution layer (Agent 2) and the voice/UI layer (Agent 3) build on.

---

## What works today

| Capability | Status | Evidence |
|---|---|---|
| Intent classification over a capability catalog | real | `tests/test_intent.py` |
| Mid-request destination correction (`"open Spotify, no wait, open YouTube"`) | real | `tests/test_intent.py`, `tests/test_lifecycle.py` |
| Multi-action requests, order preserved | real | `tests/test_intent.py` |
| Missing / ambiguous parameters -> clarification | real | `tests/test_intent.py`, `tests/test_safety.py` |
| Session isolation (two live sessions, no cross-talk) | real | `tests/test_sessions.py` |
| Pause / resume / cancel / supersede | real | `tests/test_lifecycle.py` |
| Approval + refusal for irreversible actions | real | `tests/test_safety.py` |
| Real decision model (`convaiinnovations/laya`) with observable fallback | real | `scripts/eval_laya.py`, `reports/` |
| Local execution adapters (notes, timers, browser) | real | `tests/test_tools.py` |
| Service integrations (music, coding agent, games) | **not implemented** | Agent 2 / Agent 3 |

Nothing in this repository simulates a service and calls it real. Where a
capability has no adapter yet, the API answers `tool_unavailable` and says so.

---

## Quickstart

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     POSIX: source .venv/bin/activate
pip install -e ".[dev]"               # core only (no model weights needed)
pip install -e ".[dev,laya]"          # + the real Laya decision model
sidekick                              # http://127.0.0.1:8000
```

Or without installing:

```bash
python -m uvicorn "sidekick.api.app:create_app" --factory --port 8000
```

Open <http://127.0.0.1:8000> for the Phase 1 slice page (a placeholder UI -
Agent 3 owns the real experience).

Run the tests:

```bash
python -m pytest            # 99 tests, no network and no model weights needed
```

Check that the core and the other agents still agree on the contract:

```bash
git fetch origin --prune
python scripts/check_contract_compat.py
```

Evaluate the real model (downloads ~800 MB of weights on first run):

```bash
python scripts/eval_laya.py --checkpoint typed-decisions --json reports/laya-typed-decisions.json
```

---

## Architecture

```
utterance ──► DecisionEngine ──► intent ──► SafetyPolicy ──► Action plan ──► ToolRegistry
                 │                    │             │                │
                 │                    │             │                └─► Agent 2 adapters
                 │                    │             └─ deterministic gate (risk, approval,
                 │                    │                argument validation) - the model
                 │                    │                cannot bypass it
                 │                    └─ DecisionModel: Laya (real) -> rule fallback
                 │                       (the fallback is always reported, never hidden)
                 └─ session scoped state: active task, suspended tasks,
                    pending actions, entities - isolated per session id
```

Design rules (see `.sidekick/ARCHITECTURE.md`):

- **Model interpretation is separate from deterministic safety.** The model may
  propose an action; it can never grant itself permission to run one.
- **Fallback identity is observable.** `decision_model.fallback_used` is
  `true` exactly when the real model did not produce the interpretation.
- **Sessions are isolated.** State lives under an explicit session id; two
  concurrent sessions never see each other's work.
- **Corrections supersede before execution.** An unexecuted plan is replaced
  before anything runs; an in-flight action is stopped, or reported honestly
  as still running when the adapter cannot stop it.

---

## The decision model

The intent layer uses [`convaiinnovations/laya`](https://huggingface.co/convaiinnovations/laya)
(Apache-2.0, self-hosted, non-autoregressive decision model). Laya never
generates text: it answers *typed* questions (`choice`, `score`, `noul`) with
calibrated probabilities, so there is nothing to parse and nothing to
hallucinate.

The answer space is generated from the **capability catalog** at request time,
so a new capability needs no retraining:

| Question | Type | Answer space |
|---|---|---|
| `action` | choice | the capabilities in the catalog |
| `destination` | choice | the destinations in the catalog |
| `is_correction` | noul | is this correcting an earlier request? |
| `confidence` | score | how clear is the request? |

When Laya is not installed, is too slow, or returns something unusable, the
deterministic catalog matcher takes over **and the response says so**
(`decision_model.fallback_used = true` plus the reason).

### Measured on this machine (CPU, no GPU)

`python scripts/eval_laya.py --checkpoint <name>` over the labelled set in the
script (raw output in `reports/`):

| Checkpoint | tool accuracy | with the deterministic fallback | destination accuracy | warm latency |
|---|---|---|---|---|
| `english` | 25% | 67% | 100% | ~2.0 s |
| `multilingual` | 50% | 92% | 100% | ~0.7 s |
| **`typed-decisions`** (default) | 50% | **100%** | 100% | ~1.4 s |

`typed-decisions` is the checkpoint that was fine-tuned for typed decisions,
which is exactly what this layer asks for, so it is the default.

Two measurements shaped the design:

- The model answered the *destination* question with 100% accuracy when it was
  sure and invented one with ~0.3 confidence when the utterance had no
  destination - so a destination is only used above a confidence floor.
- The model was worse at picking the capability than at picking the
  destination, and it was worse still when control verbs were in the answer
  space. So control verbs are resolved by the deterministic grammar and the
  model only chooses between capabilities.

---

## Repository layout

```
sidekick/
  core/            # the brain: schemas, catalog, registry, sessions, safety,
                   # decision models, parsing, engine
  tools/local.py   # real local adapters (notes, timers, browser)
  api/             # FastAPI app + the Phase 1 slice page
  bootstrap.py     # object graph (registry -> engine)
scripts/           # real model evaluation
tests/             # the suite behind the table above
.sidekick/         # team coordination documents (Agent 1 owns them)
```

---

## API (contract v1)

Full schema: `.sidekick/API_CONTRACTS.md`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/requests` | one user turn -> intent, action plan, events |
| `GET` | `/api/v1/capabilities` | the truthful capability inventory |
| `GET` | `/api/v1/actions/{id}` | one action and its events |
| `GET` | `/api/v1/actions/{id}/events` | SSE stream of an action's events (resumable with `?after=`) |
| `POST` | `/api/v1/actions/{id}/approve` | approve or refuse a pending action |
| `POST` | `/api/v1/actions/{id}/cancel` | cancel one pending or running action |
| `GET` | `/v1/sessions/{session_id}` | session state, tasks, actions |
| `GET` | `/v1/sessions/{session_id}/events` | the session event log |
| `GET` | `/healthz` | liveness + truthful model status |

The shorter `/v1/...` aliases exist for every route (`POST /v1/decide`, `GET /v1/tools`, ...).

Session identity: the `X-Sidekick-Session-Id` header wins over the `session_id`
body field. The rule is defined once and applied everywhere.

```bash
curl -s http://127.0.0.1:8000/api/v1/requests \
  -H 'Content-Type: application/json' \
  -H 'X-Sidekick-Session-Id: demo' \
  -d '{"request_id":"r1","session_id":"demo","utterance":"Open Spotify, no wait, open YouTube"}'
```

---

## Configuration

| Variable | Meaning |
|---|---|
| `SIDEKICK_DECISION_MODEL` | `auto` (default), `laya` or `rule` |
| `SIDEKICK_LAYA_CHECKPOINT` | `typed-decisions` (default), `english`, `multilingual` |
| `SIDEKICK_WORKSPACE` | where the local tools write (default `./sidekick_runtime`) |
| `SIDEKICK_HOST` / `SIDEKICK_PORT` | server binding (default `127.0.0.1:8000`) |
| `LAYA_PRELOAD` | `1` loads the checkpoint at start-up instead of lazily |

No secrets are read or stored by this project. See `.env.example`.

---

## Team

| Agent | Owns |
|---|---|
| Agent 1 | core brain, contracts, safety policy, session orchestration |
| Agent 2 | real execution adapters and integrations |
| Agent 3 | voice, UI, media and game experiences |
| Agent 4 | CI, contract tests, merge gate, release evidence |

Coordination documents live in `.sidekick/`. Please read
`.sidekick/TEAM_PLAYBOOK.md` before changing a shared interface.
