# Decision Failures

**Owner:** Agent 1 (core brain) · **Date:** 2026-10-21

Every failure below was **reproduced against the running application**, not reasoned about. The
reproduction is `scripts/reproduce_requests.py`; the raw output is in `reports/audit-rule.json`
(deterministic fallback) and `reports/audit-laya.json` (the real model).

Each entry has: how to reproduce it, what the brain did, the root cause, and the fix. Every fix
has a regression test.

---

## 1. The real model answered confidently and arbitrarily

**Reproduce**

```bash
python scripts/reproduce_requests.py --model laya
```

**What happened** (real model, `typed-decisions` checkpoint, CPU)

| Request | Decision | Reported |
|---|---|---|
| "Order dinner for me." | `note.read` | **succeeded** - "Reading your notes." |
| "xyzzy plugh." | `note.read` | **succeeded** - "Reading your notes." |
| "Search for flights to Delhi next Friday." | `note.read` | **succeeded** |
| "Fix the failing tests in my project." | `note.read` | **succeeded** |
| "What can you actually do?" | `note.read` | **succeeded** |
| "Play some relaxing music." | `note.read` | **succeeded** |
| "Find a good movie for tonight." | `note.read` | **succeeded** |

12 of 13 requests "succeeded". Almost all of them succeeded **wrongly**: the product claimed it had
read the user's notes when the user had asked for dinner, flights, a bug fix or its own
capabilities. This is the worst possible failure mode - it is not a refusal, it is a confident lie.

**Root cause**

The Laya checkpoint answers a `choice` question over the answer space it is given. On an answer
space it was **not** calibrated for, its confidence is meaningless. The library says so itself:

> `laya: this checkpoint ships invalid temperatures or values outside [0.5, 5]; using
> choice:11+=0.10058280825614929 -> 0.5. Treat confidence from the affected entries as
> uncalibrated.`

The engine trusted that confidence (the floor was 0.35) and the model won every turn. The earlier
measurement had already shown the checkpoint at 50% tool accuracy on this answer space - the
remaining errors were exactly the ones the engine could not see, because the model was
*confident* while being wrong.

**Fix**

The decision model may **no longer introduce a capability the utterance does not mention**
(`DecisionEngine._anchor_to_utterance`).

- the deterministic matcher decides which capabilities the utterance supports;
- the model may choose *between* those (that is where it earns its place);
- a model answer for a capability the utterance never mentions is rejected, and the deterministic
  candidate is used instead;
- if the utterance supports nothing, the answer is an honest "I do not have a capability for that
  yet" - never an arbitrary action.

**Tests** `tests/test_capabilities.py::test_the_model_may_not_introduce_a_capability_the_utterance_does_not_mention`,
`::test_the_model_may_choose_between_the_capabilities_the_utterance_supports`

---

## 2. The model invented a destination

**Reproduce** the same run: "xyzzy plugh." produced `media.open` with
`destination = "google"`, and the engine opened Google.

**Root cause** the model's `destination` answer was accepted above a confidence floor of 0.7. The
model answers a destination with 100% accuracy when the utterance mentions one, and invents one
with ~0.3 confidence when it does not - but on an uncalibrated answer space even the confident
case is unreliable.

**Fix** a destination is used only when the utterance **mentions** it (the catalog's aliases
decide). The model chooses *between* the mentioned destinations; it may not introduce one. The
confidence floor was removed because it was measuring the wrong thing.

**Tests** `tests/test_capabilities.py::test_a_destination_must_be_mentioned_in_the_utterance`

---

## 3. Every unsupported request produced the same useless answer

**Reproduce**

```bash
python scripts/reproduce_requests.py
```

"Order dinner for me.", "Find a good movie for tonight." and "xyzzy plugh." all produced:

> I did not catch which action you want. Which of these did you mean?
> `[media.open, note.read, note.set, note.write, timer.list, timer.set]`

**Root cause** one generic clarification with the internal tool names as options. It did not say
*I cannot do that*, and it did not say what the product *can* do.

**Fix** the unsupported answer now states the limitation and lists the real capabilities in human
words ("write a note", "search the web", "set a reminder", …).

**Tests** `tests/test_capabilities.py::test_an_unsupported_request_says_so_instead_of_guessing`,
`::test_nonsense_gets_the_same_honest_answer`

---

## 4. "What can you actually do?" was unanswerable

**Reproduce** the same run: the request produced the generic clarification above.

**Root cause** no capability in the catalog answered it, and no control verb matched it. The word
"actually" is a correction marker, so even a generic correction path would have eaten the
question.

**Fix** a dedicated capability question, answered from the catalog
(`sidekick/core/parsing.py::is_capability_question`). It is checked **before** the correction
handling, so "what can you actually do" is never mistaken for a correction. The answer separates
what the server does from what the browser app does.

**Tests** `tests/test_capabilities.py::test_asking_what_the_product_can_do_returns_the_inventory`,
`::test_the_capability_question_is_not_mistaken_for_a_correction`

---

## 5. A generic verb hijacked a specific capability

**Reproduce**

```bash
python -c "..."   # "show me my notes" -> media.open (missing_argument)
```

**Root cause** `media.open` had the aliases "show me", "browse" and "go to", and the matcher was a
substring test. "show me my notes" matched "show me" and became a browser launch, while
"read my notes" (the actual capability) was ignored.

**Fix**

- the over-generic aliases were removed from `media.open`; "browse" and "show me" are search
  triggers, not service names;
- the matcher is now **content-word based**: an alias matches when its content words appear in the
  utterance, with at most one filler word in between, and a more specific alias wins;
- a light stem makes "test" match "tests" and "song" match "songs";
- ties are broken by the tool name, so the result does not depend on the registration order.

**Tests** `tests/test_capabilities.py::test_a_generic_verb_does_not_hijack_a_specific_capability`,
`::test_an_alias_matches_across_a_filler_word`, `::test_a_plural_in_the_utterance_matches_a_singular_alias`

---

## 6. "list my timers" did not match "list timers"

**Reproduce** the same way: the request was unresolvable even though `timer.list` existed.

**Root cause** substring matching: the alias was "list timers" and the utterance was "list my
timers".

**Fix** the content-word matcher described above.

**Tests** `tests/test_capabilities.py::test_an_alias_matches_across_a_filler_word`

---

## 7. The catalog had no reminder and no web search

**Reproduce** "Remind me to call my friend at 6 PM." and "Search for flights to Delhi next
Friday." were both unresolvable.

**Root cause** the catalog had five capabilities: open a service, write a note, read notes, set a
timer, list timers. A *reminder* (a scheduled prompt about a specific topic) and a *search* were
not in it.

**Fix**

- `reminder.set` - a real scheduled reminder. It parses "6 PM", "6:30 pm", "in 20 minutes",
  "tomorrow at 9" and "tonight at 8" into a real local moment, schedules a real timer and
  completes the action when it is due. A bare hour is read the way people usually mean it (1-6 is
  the afternoon) and the resolved time is **spoken back**, so the assumption is visible.
- `web.search` - a real search. It builds the real search URL for the query and opens it. It is
  explicitly *a search*, not a fetch and not a booking: the spoken line says "Searching for X."

**Tests** `tests/test_capabilities.py::test_a_web_search_opens_a_real_search`,
`::test_a_search_is_not_a_booking`, `::test_a_reminder_is_scheduled_for_the_requested_moment`,
`::test_a_reminder_does_not_inherit_the_previous_reminders_time`,
`::test_the_spoken_reminder_repeats_the_moment_it_understood`

---

## 8. The core claimed capabilities it could not execute

**Reproduce** the same run. The core's catalog could not express "play music" at all, so the
request was unresolvable - and the *client* capabilities (media, movies, games) that Agent 3
implements were invisible to the brain.

**Root cause** the catalog only described things the **server** can run. The product is bigger than
the server.

**Fix** a client-capability declaration (`sidekick/client_capabilities.json`, owned by Agent 3).
The core reads it, routes to those capabilities and plans the action for the client
(`execution_target: "client"`, state `pending`, result `awaiting_client`). The client runs it and
reports the real outcome through `POST /v1/actions/{id}/complete`. The core never reports a
client capability as done before the client says so.

**Tests** `tests/test_capabilities.py::test_a_client_capability_is_planned_for_the_client_and_not_executed`,
`::test_the_client_reports_the_real_outcome`, `::test_a_client_failure_is_recorded_as_a_failure`

---

## 9. The cold start was reported as a model timeout

**Reproduce**

```bash
SIDEKICK_RUN_MODEL_TESTS=1 python -m pytest tests/test_laya_integration.py
```

The first request failed with `ModelTimeout: laya did not answer within 20.0s` and fell back to
the rule engine. The model was fine: the *first* call also builds the checkpoint, which takes
~30 s on this CPU.

**Root cause** one timeout budget for both the cold start and the steady state.

**Fix** two budgets: `first_call_timeout_seconds` (default 300 s) for the call that builds the
checkpoint, `timeout_seconds` (default 20 s) for every call after it. The rule engine is used
whenever the model is genuinely too slow.

**Tests** `tests/test_decision_models.py::test_lava_enforces_a_timeout`,
`::test_a_cold_start_gets_its_own_time_budget`

---

## 10. The audit harness opened real browser windows

**Reproduce** any run of `scripts/reproduce_requests.py`, or the real-model
integration suite.

**What happened** Chrome kept opening windows while the audit ran. The
adapters are real - `media.open` and `web.search` call `webbrowser.open` - and
the harness and two integration tests did not stub it. The audit opened 5 real
URLs; the integration tests opened Spotify and YouTube.

**Root cause** the tests treated the browser as an environment detail instead of
a side effect. A test run must have no effect on the machine it runs on.

**Fix**

- `webbrowser.open` **and** `webbrowser.get` are replaced for the whole test
  session (`tests/conftest.py`), so the real browser is unreachable;
- `tests/test_no_browser_side_effects.py` guards the rule, and
  `SIDECKICK_STRICT_BROWSER=1` turns every browser call into a failure;
- the audit harness stubs the browser by default and reports the URL it *would*
  have opened; `--real-browser` is the explicit opt-in for a manual check;
- the real-model suite is still opt-in and leaves nothing behind (the
  background workers are daemon threads).

**Verification** two full suite runs with the Chrome process count before and
after: **0 windows opened**.

**Tests** `tests/test_no_browser_side_effects.py`

---

## 11. A "did you mean" that was wrong

**Reproduce** "find a restaurant" with the first version of the near-miss
logic.

**What happened** the answer was *"Did you mean play a movie or search the
web?"* - "play a movie" for "find a restaurant" is nonsense. A loose
comparison of content words cannot tell "find a restaurant" from "find a
movie": the noun changed, and nothing deterministic knows that.

**Root cause** the near-miss rule compared *how many* words matched, which is
not the same as *whether the suggestion is right*.

**Fix** the unreliable suggestion is gone. The answer lists what the product
can do, in human words, and the reliable kind of "did you mean" is handled
where it can be: a single typo in a **service name** ("open spotfy" -> Spotify)
is resolved and the request simply works.

**Tests** `tests/test_capabilities.py`

The engine uses `confidence_floor = 0.35` to decide whether to believe the model. **That number
is a heuristic.** It was chosen from a small labelled set on one machine with one checkpoint, and
the checkpoint's own confidence is not calibrated for this answer space (see §1).

It is therefore *not* used as a statistical threshold, and the documentation says so. What the
engine actually relies on is the **anchor**: the model's answer must be supported by the
utterance. The floor is a second line of defence, not the main one.

**Tests** `tests/test_capabilities.py` (the anchor tests above)

---

---

## 12. The confidence threshold is a heuristic, not a calibration
