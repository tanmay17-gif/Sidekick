# Capability Reality Audit

**Owner:** Agent 1 (core brain) · **Date:** 2026-10-21 · **Branch:** `agent1/capability-reality`

This audit is about **what Sidekick actually does**, not about what it could do. Every row was
reproduced against the running application with
[`scripts/reproduce_requests.py`](../scripts/reproduce_requests.py) (raw output in
`reports/audit-rule.json` and `reports/audit-laya.json`).

Status vocabulary:

| Status | Meaning |
|---|---|
| `REAL` | the request runs a real adapter and a real result comes back |
| `SIMULATED` | a double stands in for the real thing (nothing in this repository is simulated in production) |
| `NOT_CONFIGURED` | the code is there but a credential or provider is missing |
| `NOT_IMPLEMENTED` | nobody has built it |

**Opening a website is not completing a task.** Opening Spotify is not finding the requested song
and playing it. Opening YouTube is not finding and playing the requested video. A search result
page is not a booking. This audit keeps that line everywhere.

---

## 0. Why it *looked* like the product only opened websites

While the audit was running, Chrome kept opening windows. That was **the audit
harness and the real-model integration tests**, not the product:

- `scripts/reproduce_requests.py` sends 13 real requests through the running
  application, and `media.open` / `web.search` are real adapters - they call
  `webbrowser.open`. The audit opened 5 real URLs (YouTube, Spotify, a Google
  search for the flights request).
- two of the six real-model integration tests did not stub the browser and
  opened Spotify/YouTube for real.

**Fixed in this branch:** the browser is now unreachable for the whole test
session (`webbrowser.open` *and* `webbrowser.get` are replaced in
`tests/conftest.py`), the audit harness stubs it by default and only opens a
real window with `--real-browser`, and `tests/test_no_browser_side_effects.py`
guards the rule. A full suite run now opens **zero** windows - verified by
counting the Chrome processes before and after.

So the *symptom* was a test/demo loop. The *product* reason it looked that way
is in the table below: the catalog's only server-side media capability was a
browser launcher.

---

## 1. The headline: what the product could do before this audit

`scripts/reproduce_requests.py` against the pre-audit build:

| Request | Decision | Outcome |
|---|---|---|
| "Open YouTube." | `media.open` | REAL - opened the browser |
| "Play some relaxing music." | *unresolved* | generic clarification |
| "Find a good movie for tonight." | *unresolved* | generic clarification |
| "Remind me to call my friend at 6 PM." | *unresolved* | generic clarification |
| "Write a note saying…" | `note.write` | REAL - wrote a file |
| "Help me debug this Python error." | *unresolved* | generic clarification |
| "Fix the failing tests in my project." | *unresolved* | generic clarification |
| "Search for flights to Delhi next Friday." | *unresolved* | generic clarification |
| "Order dinner for me." | *unresolved* | generic clarification |
| "Stop what you're doing." | `control.cancel` | REAL - cancelled |
| "No, I meant Spotify, not YouTube." | `media.open` | REAL - opened Spotify |
| "What can you actually do?" | *unresolved* | **generic clarification** |
| "xyzzy plugh." | *unresolved* | generic clarification |

**4 of 13 requests did anything.** Every unsupported request produced the same useless
"I did not catch which action you want. Which of these did you mean?" with a list of internal tool
names, and the single most important question a user can ask - *what can you do?* - was itself
unanswerable.

Worse: with the **real Laya model** the same run produced **12 of 13 "succeeded"** - and almost
every one of them succeeded *wrongly*. "Order dinner for me" and "xyzzy plugh" both ran
`note.read` ("Reading your notes.") and reported success. The model was not making the product
useful; it was making it confidently wrong. See `docs/DECISION_FAILURES.md` §1.

---

## 2. The capability table

### 2.1 Browser and web search

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Search the web for python tutorials" | `web.search` | `WebSearchTool` | **REAL** | Opens the real Google results page for the query. The result carries the query, the engine and the URL | It is a *search page*, not a fetched answer. No content is read, summarised or returned to the conversation | A real content fetch belongs to Agent 2's `web.fetch` (on `agent2/core-integration`) - the core should prefer it when it is registered |
| "Search for flights to Delhi next Friday" | `web.search` | `WebSearchTool` | **REAL (as a search)** | Opens the real search results for "flights to Delhi next Friday" | **No booking, no comparison, no airline.** The core does not have a travel provider and must never imply that it booked anything | A travel provider (credentials + money) - **no owner yet** |
| "Open YouTube" | `media.open` | `MediaOpenTool` | **REAL** | Opens `https://www.youtube.com` in the system browser | It opens the *home page*. It does not search, it does not play the requested video | Playback/search is Agent 3's (client) - see §2.2 |
| "Open spotfy" (a typo) | `media.open` | `MediaOpenTool` | **REAL** | The single typo is resolved to Spotify and the real Spotify page opens | - | - |
| "Inspect my open browser tabs" | *unresolved* | - | **NOT_IMPLEMENTED** | Honest "I do not have a capability for that yet" | A browser extension or the WebExtension API. Not declared anywhere | **No owner.** Deliberately not declared: declaring it would offer a capability that then fails |

### 2.2 YouTube, Spotify, music and media control

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Open Spotify" | `media.open` | `MediaOpenTool` | **REAL** | Opens `https://open.spotify.com` | **This is not music playback.** No track is searched, chosen or played | Agent 3: `media.play` is declared in `sidekick/client_capabilities.json`; the client must run it and report the outcome via `POST /v1/actions/{id}/complete` |
| "Play some relaxing music" | `media.play` (client) | browser client | **NOT_IMPLEMENTED (client)** | The core plans the action and waits (`awaiting_client`) | The client has to execute it and report back. The core never claims it played anything | Agent 3 |
| "Pause the music" / "resume" | `control.pause` / `control.resume` | core | **REAL for the core's own tasks** | Suspends and resumes the core's *running* task. It does not pause a track in a player | A client-side media controller that honours the pause | Agent 3 (with the `control.pause` action routed to the client) |
| "Play the video I asked for" | `media.open` | `MediaOpenTool` | **REAL only as "open the app"** | Opens the app home page | Search + playback | Agent 3 |

### 2.3 Notes, reminders and timers

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Write a note saying I need to finish the hackathon" | `note.write` | `NoteWriteTool` | **REAL** | Writes a real file under the workspace and reports the path | - | - |
| "Read my notes" | `note.read` | `NoteReadTool` | **REAL** | Reads the real files back | - | - |
| "Set a timer for 5 minutes" | `timer.set` | `TimerSetTool` | **REAL** | A real background timer; the action stays `running` and completes when it fires; it can be cancelled while it runs | - | - |
| "List my timers" | `timer.list` | `TimerListTool` | **REAL** | Lists the real scheduled timers | - | - |
| "Remind me to call my friend at 6 PM" | `reminder.set` | `ReminderSetTool` | **REAL** (new) | Parses the moment ("6 PM" -> 18:00 local, "in 20 minutes", "tomorrow at 9"), schedules a real timer and completes the action when it is due | **The reminder only lives in the running process.** It is not delivered to a phone and it is lost on a restart - the result says so (`delivery: "in-process; a restart loses the reminder"`) | A push/notification channel - **no owner** |

### 2.4 Coding, file edits, tests and debugging

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Fix the failing tests in my project" | *unresolved* | - | **NOT_IMPLEMENTED** (in `main`) | Honest "I do not have a capability for that yet" | The `coding.execute` adapter | **Agent 2** has it on `agent2/core-integration` (`sidekick/tools/execution.py`): a real sandbox, real edits, a real `git diff` and the real test exit code. It is not in `main` yet |
| "Help me debug this Python error" | *unresolved* | - | **NOT_IMPLEMENTED** (in `main`) | Same | The same adapter, plus an alias that matches "debug" | **Agent 2**: `coding.execute`'s aliases are "write code", "fix the bug", "fix the failing test", … - "debug" is not among them. One line in their `ToolSpec` would cover it |
| (with the execution service running) | `coding.execute` | `ExecutionServiceAdapter` | **NOT_CONFIGURED** | The core asks for approval, the action reaches the service, the service reports `provider_not_configured` | **A credential.** No `SIDEKICK_LLM_API_KEY`, no `OPENAI_API_KEY`, no `ANTHROPIC_API_KEY` and no coding CLI (`claude`, `codex`, `aider`, `cursor-agent`, `copilot`, `gemini`, `ollama`) exist on any agent's machine | **Agent 2 / the team:** pick an LLM API key or install a coding CLI. The executor is real and verified; only the *model that decides the change* is unverified |

### 2.5 Movies and the movie companion

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Find a good movie for tonight" | `movie.play` (client) | browser client | **NOT_IMPLEMENTED (client)** | The core plans it and waits (`awaiting_client`) | The client must run it | Agent 3 owns the movie companion and the bundled open-licensed film. The core's `movie.play` capability is a *declaration*, not an implementation |
| "Play a movie" | `movie.play` (client) | browser client | **NOT_IMPLEMENTED (client)** | Same | Same | Agent 3 |

### 2.6 Games and other client-side capabilities

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Start chess" | `game.start` (client) | browser client | **NOT_IMPLEMENTED (client)** | The core plans it and waits | The client must run it | Agent 3 (chess and the other local games are already in their branch) |

### 2.7 Flights, food ordering, bookings and other external transactions

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Search for flights to Delhi next Friday" | `web.search` | `WebSearchTool` | **REAL as a search only** | Opens the real search page | No search API, no price, no booking, no airline contact | A travel API + credentials + the user's payment method. **No owner.** The core must not pretend a search is a booking |
| "Order dinner for me" | *unresolved* | - | **NOT_IMPLEMENTED** | Honest "I do not have a capability for that yet" | A food delivery provider, an account, a payment method, and a legal basis for spending the user's money | **No owner.** Deliberately not declared: an ordering capability needs a real provider, a real account and an explicit money policy before it may exist |

### 2.8 Voice, corrections, interruptions and sessions

| User request | Current decision | Execution adapter | Status | What actually happens | What is missing | Fix / owner |
|---|---|---|---|---|---|---|
| "Open YouTube, no wait, open Spotify" | `media.open` | `MediaOpenTool` | **REAL** | Only Spotify is opened; the stale destination never runs and the superseded action stays visible in the plan | - | - |
| "No, I meant Spotify, not YouTube" | `media.open` | `MediaOpenTool` | **REAL** | Opens Spotify and says "Opening Spotify instead." | - | - |
| "Cancel that and echo hello instead" | `control.cancel` + `test.echo` | core | **REAL** | Cancels the pending work *and* runs the new instruction | - | - |
| "Continue what I was doing before" | resume | core | **REAL** | Resumes the suspended task without replaying finished steps | Session state is in memory; a restart loses it | Durable session storage - Phase 4 hardening |
| "Stop what you're doing" | `control.cancel` | core | **REAL** | Cancels the running action. If the adapter cannot stop it, the action becomes `paused` with `cancellation_unsupported` and the answer says the work may still be running | - | - |
| "yes" / "no" after a confirmation | `control.confirm` / `control.reject` | core | **REAL** | Approves or refuses the exact pending action | The voice path should prefer the explicit `POST /v1/actions/{id}/approve` so the binding to the exact action is guaranteed | Agent 3 |
| "What can you actually do?" | `control.capabilities` | core | **REAL** (new) | Answers with the whole inventory, separating what the server does from what the app does | - | - |
| Spoken answer | `speech` | core | **REAL** | A short, truthful line ("Opening Spotify instead.", "Reminder set for 6 pm.") | - | Agent 3 speaks it verbatim |

---

## 3. What the *core* owns versus what the rest of the product owns

| Area | Owner | How the core learns about it |
|---|---|---|
| Intent, safety, sessions, the contract | Agent 1 | - |
| Coding execution, web fetch, system inspection | Agent 2 | an adapter registers itself against `ToolAdapter`; the core picks it up from the registry |
| Media, movies, games, voice I/O | Agent 3 | `sidekick/client_capabilities.json` - a declaration the core reads. The core plans the action, the client runs it and reports back |

The client declaration is deliberately **not** an executable capability. The core marks those
actions `awaiting_client` and never reports them as done until the client reports the real outcome
through `POST /v1/actions/{id}/complete`.

### The trust boundary, stated plainly

- The core **plans** a client capability, applies the safety policy and asks for the approval.
- The browser client **runs** it and reports what happened.
- The core **records** the report. It cannot independently verify that a browser really played a
  track or really started a game - the client's report is the only evidence. That is why the
  capability report says the client side is `client` and never `live`, and why the spoken line for
  a pending client action is "The app will play ..." rather than "Playing ...".
- A client action that is never reported fails after 120 s with `client_timeout` instead of
  hanging. A failed, cancelled or timed-out client action is never announced as successful.

---

## 4. Explicitly not implemented, not configured or not verified

Named here so that no demo claims them:

| Item | State | Why |
|---|---|---|
| **Alexa+ integration** | **NOT_IMPLEMENTED** | There is no Alexa+ skill, no account and no verified access. The voice experience in this repository is the browser Web Speech API. It is not Alexa+. |
| **AWS Bedrock** | **NOT_CONFIGURED** | The decision model is the self-hosted `convaiinnovations/laya` checkpoint. No Bedrock model is configured, called or tested. |
| **AWS deployment** | **NOT_IMPLEMENTED** | The core runs as a local process. No AWS account, no deployment, no infrastructure. |
| **A real coding provider** | **NOT_CONFIGURED** | Agent 2's executor is real and verified, but no `SIDEKICK_LLM_API_KEY` and no authorized coding CLI exist on any machine, so the *model that decides the change* has never run. |
| **A content fetch behind the web search** | **NOT_IMPLEMENTED** in the core | `web.search` opens the real results page and says so; it does not read, summarise or verify the content. Agent 2's `web.fetch` is the piece that would. |
| **Flight, food and booking providers** | **NOT_IMPLEMENTED**, no owner | They need a real provider, an account and a money policy. The core refuses them honestly. |
| **Reminders that reach a phone** | **NOT_IMPLEMENTED** | The reminder lives in the running process and is lost on a restart. The result says so. |

---

## 5. The gaps that matter, in order

1. **The model was confidently wrong and the product believed it.** Fixed in this branch: the
   decision model may no longer name a capability the utterance does not mention
   (`docs/DECISION_FAILURES.md` §1).
2. **The catalog was too narrow.** Added `web.search` and `reminder.set`; the client capabilities
   (media, movie, games) are now declared instead of missing.
3. **Capability discovery did not exist.** "What can you actually do?" now answers from the
   catalog.
4. **Unsupported requests produced a useless answer.** They now say "I do not have a capability for
   that yet" and list what *is* possible, in human words.
5. **The routing hijacked requests.** "show me my notes" opened a browser; "list my timers" did not
   match "list timers". Fixed with content-word matching, a light stem and a specificity order.
6. **No coding capability in `main`.** Agent 2's `agent2/core-integration` branch has it; it needs
   a credential to be more than a real executor.
7. **No travel, food or booking capability, and no owner.** These need real providers, accounts and
   a money policy. The core will not invent them.
