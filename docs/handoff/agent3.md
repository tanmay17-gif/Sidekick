# Agent 3 handoff - voice / chat experience, browser client

**Status:** work is complete, committed and pushed. The branch is open for the
integrator. Nothing was merged by me.

This is the handoff for the single agent who takes over Sidekick. It records
what Agent 3 owns, what is verified, what is not, and what to do next.

---

## 1. Branch, commit, PR

| | |
|---|---|
| Branch | `agent3/voice-experience` |
| Latest commit | see `git rev-parse agent3/voice-experience` (the commit that adds this file) |
| PR | <https://github.com/tanmay17-gif/Sidekick/pull/1> - **open, not merged** |
| Base | `main` @ `fcd2427` |
| Merge state at the time of writing | `mergeable: true`; CI green on the head commit |
| Owned paths | `web/**` only. No core file, no execution file, no `.sidekick/` contract file was modified. |

The PR body carries the milestone report and the merge-gate checklist for the
project owner / Agent 1. The PR is **left open on purpose**.

## 2. Commits made in this final handoff window

| Commit | What it does |
|---|---|
| `680719e` | `feat(web): Movie Buddy becomes caption-driven and adaptive` - the adaptive commentary engine, the providers, the honesty labels, the subtitle loader, the new tests, the documentation. |
| (this commit) | `docs: the Agent 3 handoff` - this file. |

Earlier commits on the same branch (19 in total) are the voice-first
Interface A, the Control Room (Interface B), the action-state bug fixes, the
public-domain demo film and the voice design system.

## 3. Files changed, and why

### The Movie Buddy rewrite (`680719e`)

| File | Purpose |
|---|---|
| `web/src/lib/movie/context.ts` | **new.** Cue windows (previous / current / upcoming / recent), `lastStartedCue`, observable properties of a line (question, emphasis, sound, length, new terms, repeated phrases), and `alignmentReport` (does the subtitle track match this copy of the film?). |
| `web/src/lib/movie/provider.ts` | **new.** The `CommentaryProvider` contract and three implementations: `createModelProvider` (any OpenAI-compatible endpoint; cancellable, timed out, rate limited, JSON-answer validated), `createLocalProvider` (the deterministic fallback), `createUnavailableProvider` (a film with no captions). `parseModelRemark` rejects an answer that is not JSON, is too long to speak, or names a cue the provider was never shown. |
| `web/src/lib/movie/engine.ts` | **new.** `BuddyEngine` - the policy: which line to talk about, when to stay silent (dialogue on screen, a line doing the work, the same moment already handled, the speaking budget, the cooldown, quiet mode), the provider rate limit, and the remark's recorded reason. |
| `web/src/lib/movie/buddy.ts` | Rewritten. It now holds **only** the grounded answers ("what just happened", "explain that moment"), which quote the captions and say plainly when there is nothing to quote. The hardcoded reaction lines and the English-verb rule list are gone. |
| `web/src/lib/media/useMovieBuddy.ts` | Rewritten around the engine. The player state, the cue state, the provider resolution, the alignment report, the remark log, the decision reason, and the re-evaluation after a seek / pause / resume / subtitle change. |
| `web/src/components/MovieBuddy.tsx` | Rewritten. The subtitle file loader, the honest source label, the alignment notices, the "why did Sidekick react" panel with the grounding, the remarks log with its source, the "no caption track" notice. |
| `web/src/lib/media/useMovieCompanion.ts` | **deleted.** Dead code from milestone 2 (only referenced by itself). |
| `web/src/components/MovieCompanion.tsx` | **deleted.** Dead code from milestone 2 (only referenced by itself). |
| `web/src/styles/components.css` | The commentary-source note stacks properly. |
| `web/tests/unit/movie-engine.test.ts` | **new.** 35 tests over two synthetic films ("The Lighthouse", "The Express" - no shared vocabulary) with a deterministic fake model. |
| `web/tests/unit/buddy.test.ts` | Rewritten for the grounded answers. |
| `web/tests/unit/movie-buddy.test.tsx` | Rewritten for the new component API (remarks, source, alignment, subtitle loading, provider injection). |
| `web/tests/e2e/app.spec.ts` | Updated: the companion now remarks in the gap after a line, the source label is checked, and the subtitle loader is checked. |
| `web/scripts/screenshots.mjs` | Fixed for the real core (`.task-card`, the Developer tab) and the new remark moment. |
| `web/README.md`, `web/docs/EXPERIENCE.md`, `web/docs/DEMO.md`, `web/docs/MOVIE_SOURCES.md` | The adaptive pipeline, the provider configuration, the honest claim levels, the demo script and the limits. |

### Why the old behaviour was wrong

`reactToCue` in `web/src/lib/movie/buddy.ts` returned one of six fixed
strings - `"Hi. Watching with you."`, `"Right - here is the plan."`,
`"Listen to that."`, `"Same idea again, slightly different."`,
`"Step by step."`, `"That is the end of it."` - chosen by a rule list. Two of
the rules were English-verb specific (`IMPERATIVE`, and
`we are going to|we'll|let's`) and were tuned to the narration of *Duck and
Cover*. There was no model call anywhere in the client, the caption context
was used only for a word-overlap check, and what Sidekick said did not depend
on what the captions said. The unit test now asserts that those strings never
appear.

## 4. Exact commands run, and their results

Run from `web/` with Node 22.23.3 (`C:\Users\admin\AppData\Local\Programs\nodejs`,
`npm.cmd` - the PowerShell execution policy blocks `npm.ps1`).

| Command | Result |
|---|---|
| `npm run lint` | 0 problems |
| `npm run typecheck` | 0 errors |
| `npm run test` | **162 passed** (12 files) - run three times in a row, green each time |
| `npm run build` | clean, 64 modules, `dist/` produced |
| `npm run verify` | green (lint + typecheck + test + build) |
| `npx playwright test` | **27 passed** (1 worker, Chromium) |
| `node scripts/verify-real-backend.mjs http://127.0.0.1:4178 http://127.0.0.1:8040` | **13/13 PASS** against the merged core (`main` @ `fcd2427`) |
| `node scripts/verify-real-flow.mjs http://127.0.0.1:4178 http://127.0.0.1:8040` | **13/13 PASS** against the merged core |
| `node scripts/verify-real-backend.mjs http://127.0.0.1:4180 http://127.0.0.1:8060` | **13/13 PASS** against **Agent 1's open branch** `agent1/capability-reality` @ `d476a76` |
| `node scripts/verify-real-flow.mjs http://127.0.0.1:4180 http://127.0.0.1:8060` | **13/13 PASS** against Agent 1's open branch |

The real backend was run from the repository checkout
(`python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1
--port 8040`) with FastAPI + uvicorn installed into a throwaway virtualenv.
Agent 1's branch was run from a **detached** worktree at `d476a76` - their
branch was not checked out, modified or pushed.

## 5. Real integrations versus mocks

**Real (a real service on a real port):**

- the two `verify-real-*.mjs` scripts, against the **merged core** and against
  **Agent 1's open core branch** - real HTTP, real requests, real actions, a
  real note written to disk, a real cancel that the core answered with
  `cancelled`, a real event stream, real ids in the developer view;
- the Playwright suite - a real Chromium against the real production build,
  real media decoding, a real playback clock, a real caption track;
- the caption files of the bundled films are the real `.srt` files, fetched
  over HTTP and parsed.

**Mocked or simulated (and labelled as such in the product):**

- the Playwright suite talks to `dev/stub-server.mjs`, which reports
  `mode: "stub"` and is labelled `DEV STUB` in the interface;
- the Movie Buddy commentary provider in every automated test is a
  deterministic fake (`createFakeModel`) or the local heuristic. **No real
  model provider was ever called** - there are no credentials for one in this
  repository, and none are required for the suite to pass;
- the chess and approval sequences are exercised against the stub, because
  the real core declares no chess tool and no tool with
  `approval_required: true`.

**Never faked:** the source of a remark. The interface shows `model`,
`local heuristic` or `unavailable`, and it shows it for the last remark, in
the remarks log and in the "why" panel.

## 6. Known bugs, limitations, risks

**Limitations (by design, and stated in the interface):**

1. Movie Buddy reads **captions only**. There is no visual analysis, no
   off-screen action, no character intention, no plot knowledge.
2. It works on a video playing **in this app**. It cannot read another
   browser tab, a streaming service or the system audio.
3. With no model provider configured the commentary is the **local
   heuristic**. It is genuinely useful (it reports a repeated phrase, new
   vocabulary, a sound, a question) but it is not a language model, and the
   interface says so.
4. The local heuristic's "new vocabulary" signal is English-word shaped. The
   *model* path is language-agnostic; the fallback is not.
5. The subtitle file the user loads is parsed **in the browser** and never
   uploaded - that is a privacy property, but it also means a very large
   subtitle file is parsed on the main thread.

**Risks for the next agent:**

6. The commentary provider talks to an **OpenAI-compatible endpoint from the
   browser**. If `VITE_SIDECKICK_COMMENTARY_API_KEY` is set, the key is in
   the client bundle. Do not put a production key there - prefer a server
   side route (see the contract dependency below).
7. `web/src/lib/media/useMovieBuddy.ts` keeps the last 24 remarks in memory
   and the engine keeps a `seen` set of cue indexes for the session. Both are
   bounded; neither is persisted.
8. The engine's speaking budget is per wall-clock minute, not per film
   minute. A viewer who seeks around can spend the budget faster. That is
   intentional (it protects the listener) but it is a policy choice, not a
   bug.
9. `alignmentReport` compares the caption coverage with the media duration.
   A film whose captions deliberately stop early (a credit sequence with no
   dialogue) is reported as a *possible* mismatch. The wording is
   deliberately hedged ("may not match").

## 7. Contract dependencies on the other agents

**On Agent 1 (core, PR #13 - `agent1/capability-reality` @ `d476a76`):**

1. `GET /api/v1/capabilities` - my client reads `capabilities[]` and
   `tools[]`. Agent 1's new `client_capabilities[]` list is **additive**: my
   client ignores it, and the contract change is backward compatible. The
   next agent should render it (the state is `client`, which is not in my
   client's state map).
2. `POST /api/v1/actions/{id}/complete` - **not implemented by me yet.** This
   is the new contract for a capability the *browser* runs. It needs
   `POST /api/v1/actions/{action_id}/complete` with
   `{ session_id, status, result, error }`. My client does not claim any
   client capability yet, so there is nothing to complete.
3. `sidekick/client_capabilities.json` - Agent 1 shipped a default and
   explicitly said the file and its wording are Agent 3's to own. It is
   **not** edited by me. The three questions Agent 1 asked are still open:
   the argument names per capability (`media.play`, `movie.play`,
   `game.start`), the result payload the client returns, and whether the
   aliases should be my wording.
4. The core now serves `web/dist` at `/` when a build is present. My build
   works when served that way (the SPA fallback is in the core, not in my
   app), but the core's fallback route is new - **verify it in a browser**
   before a demo.
5. The approval path is already bound to the `plan_hash` the core returned
   (`POST /api/v1/actions/{id}/approve` with `{ session_id, approved,
   plan_hash }`), as Agent 1 asked.

**On Agent 2 (execution service, PR #4 - `agent2/execution-foundation` @ `39bccea`):**

6. No contract change on that branch affects my client: the route table is
   identical to `main`, and the action result still carries `changed_files`,
   `diff` and `test_result`, which my client renders.
7. The execution service was **not reachable** from this environment, so the
   coding-job path (diff + test result end to end) is still
   `REAL_BUT_UNVERIFIED` in my documentation. It is the one claim in
   `web/docs/EXPERIENCE.md` that is not proven.

## 8. Environment variables and credentials

No credential is required for the normal test suite, the build or the demo.

| Variable | Needed for | Secret? |
|---|---|---|
| `VITE_SIDECKICK_COMMENTARY_ENDPOINT` | a real model-backed commentary provider (OpenAI-compatible chat completions URL) | no |
| `VITE_SIDECKICK_COMMENTARY_MODEL` | the model name sent with that request | no |
| `VITE_SIDECKICK_COMMENTARY_API_KEY` | the bearer token for that endpoint | **yes - do not set it in a browser build with a production key** |
| `VITE_SIDECKICK_COMMENTARY_TIMEOUT_MS` | the provider timeout (default 8000) | no |
| `VITE_SIDECKICK_API_BASE`, `VITE_SIDECKICK_*_PATH` | pointing a deployed build at a backend | no |
| `SIDECKICK_API_TARGET` | the dev proxy target | no |

The GitHub token used to read and update the PRs was read from a local file
and is **not** in the repository. Nothing in this branch contains a secret.

## 9. Exact next steps for the single agent

1. **Merge gate.** PR #1 is green and mergeable. Check CI, then squash-merge
   it. The checklist is in the PR body.
2. **Sequence.** Agent 1's PR #13 changes the core; Agent 2's PR #4 wires
   the execution service. Merge #13 and #4 first if the order matters, then
   #1 - or #1 first, since it only *adds* the client capabilities list on
   top of a contract my client already satisfies. My branch was verified
   against both `main` and Agent 1's branch head, so either order works.
3. **Implement the client-capability contract** (the open item from Agent 1):
   - render `client_capabilities[]` in the Control Room capability table
     (add a `client` tone to the state map in
     `web/src/lib/ui/language.ts` / the capability bar);
   - decide the argument names and the result payload, and write them into
     `sidekick/client_capabilities.json` (Agent 1's file, my wording);
   - implement `POST /api/v1/actions/{id}/complete` in
     `web/src/lib/api/client.ts` and report the real outcome of a client
     capability. The rule is the core's: **only a client capability may be
     completed by the client**, and the core records the report without
     verifying it - so never report a success the client did not observe.
4. **A real provider.** Set `VITE_SIDECKICK_COMMENTARY_ENDPOINT` against a
   local or hosted OpenAI-compatible server and run the Movie Buddy once.
   The validation (JSON, length, grounding) is already covered by unit
   tests with a fake; a real run proves the wire format.
5. **Prefer a server-side commentary route** over a browser key - see the
   risk in §6.6.
6. **Re-verify after any merge**:
   ```bash
   cd web
   npm install && npm run verify && npx playwright test
   # against the merged core
   python -m uvicorn sidekick.api.app:create_app --factory --host 127.0.0.1 --port 8040
   SIDECKICK_API_TARGET=http://127.0.0.1:8040 npm run build && npx vite preview --port 4178
   node scripts/verify-real-backend.mjs http://127.0.0.1:4178 http://127.0.0.1:8040
   node scripts/verify-real-flow.mjs http://127.0.0.1:4178 http://127.0.0.1:8040
   ```
7. **Do not delete the `web/public/media` assets.** The films and their
   caption tracks are bundled and the rights evidence is in
   `web/docs/MOVIE_SOURCES.md`.

## 10. Committed but not merged

Everything on `agent3/voice-experience` is committed and pushed but **not
merged**: 19 commits, 94 changed files. The branch is the complete Agent 3
contribution. PR #1 must not be closed by me - the merge is the integrator's
decision.

## 11. Local state I could not preserve or verify

- The throwaway Python virtualenv, the two local core processes (ports 8040
  and 8060) and the two `vite preview` processes (ports 4178 and 4180) were
  running in this shell. They are environment state, not repository state,
  and they end with the shell.
- The detached worktree used to run Agent 1's branch was removed after the
  verification; Agent 1's branch itself was never checked out, modified or
  pushed.
- **Nothing in the repository was lost.** The working tree was clean and the
  branch was in sync with the remote before this document was added.
