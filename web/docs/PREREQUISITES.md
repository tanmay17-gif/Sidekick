# A3-AUDIT - UI, voice and media prerequisites inventory

Phase 0 task `A3-AUDIT` (owner: Agent 3). Everything below was **observed on a
real machine or verified against a live host**, not inferred.

Last verified: 2026-10-21, Windows 11 dev PC.

## 1. Toolchain on the team PCs

| Tool | Status on this PC | What Agent 3 needed it for |
|---|---|---|
| `git` | Present at `C:\Program Files\Git\cmd\git.exe` (was **not** on `PATH`; `git` alone failed) | Branching, PRs |
| `gh` (GitHub CLI) | **Absent** | Used the REST API directly instead - see section 6 |
| `node` / `npm` | **Absent by default.** Installed Node **v22.23.3** (npm 10.9.9) as a portable zip | Vite build, Vitest, Playwright |
| Python | 3.13.14 present (Agent 1's observation) | Backend, owned by Agents 1/2 |

### Action items

1. **Node 22 LTS on every PC.** The `web/` package needs it. A portable zip
   works without admin rights - that is how it was installed here
   (`node-v22.23.3-win-x64` unpacked locally, then added to the user `PATH`).
   The install used for this work lives under the temp directory and is **not
   durable** - it should be reinstalled somewhere permanent.
2. **`npm.ps1` is blocked by the PowerShell execution policy** on this machine
   (`npm.ps1 cannot be loaded because running scripts is disabled`). Use
   `npm.cmd` / `npx.cmd`, or relax the policy for `CurrentUser`. This bites any
   agent that shells out to `npm`.
3. **Add `git` and `node` to `PATH`** on the other three PCs. The playbook's
   first-start protocol fails on the very first command otherwise.

## 2. GitHub access

- The repository is **public**, so cloning and reading work without
  credentials. **Pushing does not.**
- This PC had **no GitHub credentials** at all: no `~/.git-credentials`, no
  Windows Credential Manager entry, no `gh` login. `git-credential-manager`
  is installed (`C:\Program Files\Git\mingw64\bin\git-credential-manager.exe`)
  and works, but it needs `git.exe` on `PATH` or it throws.
- GCM's browser OAuth flow could not be completed from the automation browser
  (no signed-in GitHub session in that profile), and GCM's device-code endpoint
  returned 404 for its client id.
- **Working path used:** a classic personal access token (90-day expiry,
  `repo` + `workflow` scopes), stored with `git credential approve` into
  Windows Credential Manager. It is never written to a file in the repository.
- **Action item:** every agent PC needs its own token, or one shared token
  stored per machine. `gh` would make this simpler (`gh auth login`); it is not
  installed.

### Repository settings issue

The repository's **default branch is `agent1/bootstrap-protocol`**, not `main`.
Tracked as issue #2. It is a repository setting that Agent 1 owns.

## 3. Voice prerequisites

### What the browser gives us

| Capability | Chromium | Firefox | Safari | Notes |
|---|---|---|---|---|
| `SpeechRecognition` | Yes | Inconsistent | Inconsistent | Chromium's implementation is a **cloud service** - audio leaves the device and it does not work offline |
| `speechSynthesis` | Yes | Yes | Yes | Voice list is populated asynchronously; Chromium stops long utterances after ~15s |
| `navigator.permissions.query({name:'microphone'})` | Yes | No | No | The client treats `null` as "unknown" and falls back to the engine's own errors |
| `getUserMedia` / `MediaDevices` | Yes | Yes | Yes | Not required - the Web Speech API opens its own stream |

### Observed behaviour worth designing around

- Chromium's error codes map to distinct, recoverable states: `not-allowed`,
  `service-not-allowed`, `audio-capture`, `no-speech`, `network`, `aborted`,
  `language-not-supported`. The client gives each one its own message.
- `service-not-allowed` is the usual private-window / blocked-third-party-script
  failure, **not** a microphone permission problem. The two need different
  copy.
- When no system voice is installed, `speechSynthesis.speak()` never fires
  `onstart` **or** `onend`. Without a watchdog the interface would sit in
  "speaking" forever. This was observed in headless Chromium and is now
  covered by a test.

### Demo implications

- **Chromium is the demo browser.** Everything voice-related was verified
  there.
- The text path is a **first-class fallback**, not a debug mode, because
  Safari/Firefox users and anyone on a locked-down machine will need it.
- **No Alexa+ integration exists.** The Web Speech API is not Alexa+ and must
  not be presented as such. See `EXPERIENCE.md`.

## 4. Media prerequisites

### Verified sources

| Asset | Host | Verified |
|---|---|---|
| Tears of Steel 720p MP4 | `archive.org/download/Tears-of-Steel/tears_of_steel_720p.mp4` | 76,435,802 bytes, `Content-Type: video/mp4`, `Accept-Ranges: bytes`, `Access-Control-Allow-Origin: *`, **faststart** (`moov` at byte 36, `avc1` at 24, `mp4a` at 142,628) |
| Tears of Steel English subtitles | `download.blender.org/demo/movies/ToS/subtitles/TOS-en.srt` | 4,764 bytes, 76 cues, 00:00:23 -> 00:09:27 |

### Negative results (so nobody repeats the search)

- `media.w3.org` serves `sintel/trailer.mp4` and `bunny/trailer.mp4` but **no
  matching subtitle track** at any of the usual paths, and sends **no CORS
  header**.
- `download.blender.org` sends **no CORS header**, so the browser cannot
  `fetch()` the `.srt` from it directly. This is why the subtitle file is
  **vendored into the repository** and parsed client-side.
- `archive.org` **does** send `Access-Control-Allow-Origin: *`, so a
  backend-provided media catalog can be fetched cross-origin.
- The Blender `.mov` (372 MB, `moov` at the end of the file) works but forces
  a tail request before playback starts. The Internet Archive MP4 derivative
  is 5x smaller and faststart, so it is the one used.

### Codec note

The Internet Archive MP4 is H.264/AVC in an MP4 container - it plays in
Chromium, Firefox and Safari. The `.mov`/`.mkv` originals are not a safe
default for a browser demo.

### Licensing

Tears of Steel is **CC BY 3.0** (Blender Foundation / MPEG). The subtitle file
is redistributed in this repository under the same licence with attribution in
the UI and in `EXPERIENCE.md`. The video is streamed, not vendored. No
copyrighted material is scraped or redistributed by this client.

## 5. Backend prerequisites for the browser

The client needs these from the Core/Execution agents:

| Need | Contract | Status |
|---|---|---|
| Submit an utterance | `POST /api/v1/requests` (path proposed in `CONTRACT_NOTES.md`) | Backend not built yet |
| Capability inventory | `GET /api/v1/capabilities` | Backend not built yet |
| Optional media catalog | `GET /api/v1/media/catalog` | Backend not built yet |
| Session identity | `x-sidekick-session-id` header, falling back to `body.session_id` | Implemented on the client |
| Response envelope | `SidekickResponse` from `API_CONTRACTS.md` v1 | Implemented on the client |
| Streaming progress | `text/event-stream` frames ending in the final response | Implemented on the client, exercised against the dev stub |
| Error envelope | `{ error: { code, message, retryable, timeout } }` | Implemented on the client |

Until the real backend exists, `web/dev/stub-server.mjs` answers the same
contract and reports `mode: "stub"`, so the interface labels it honestly.

## 6. Tooling notes for the other agents

- **No `gh` CLI.** Everything in this PR was done with `curl` against the
  REST API (`POST /pulls`, `POST /issues/{n}/comments`). Installing `gh` would
  remove a lot of friction.
- **`curl.exe` is available** on Windows and is the reliable way to POST JSON
  to the GitHub API - `Invoke-RestMethod` mangles the body when the payload
  file has a UTF-8 BOM, and `ConvertTo-Json` + `Set-Content` writes one.
- **Playwright browsers** install with `npx playwright install chromium`
  (~90 MB). On the CI runner the primary download host was unreachable and the
  fallback mirror was used automatically - the workflow still succeeded.
- **CI binding:** `vite preview` binds `localhost`, which on the Ubuntu runner
  resolved to `::1` only, so the IPv4 base URL got `ECONNREFUSED`. The E2E
  config now passes `--host 127.0.0.1` explicitly.

## 7. Summary of open prerequisites

| # | Prerequisite | Owner | Blocking |
|---|---|---|---|
| 1 | Node 22 LTS installed permanently on all four PCs | Everyone | Building and testing `web/` |
| 2 | GitHub credentials on each PC (or `gh auth login`) | Everyone | Pushing branches and opening PRs |
| 3 | Default branch switched back to `main` | Agent 1 | PR targets, clone ergonomics |
| 4 | Real backend endpoints matching the v1 contract | Agents 1/2 | The app running against real services |
| 5 | Music provider credentials (optional) | Agent 2 | Live music playback |
| 6 | Repository `LICENSE` and root `README.md` | Agent 1 / Agent 4 | Open-source deliverable |
