# Demo walkthrough - Sidekick browser client

A short, honest script for demonstrating the browser surface. Every step below
shows something the interface really did - nothing is scripted animation.

## Before you start

```bash
cd web
npm install
npm run stub     # terminal 1 - SIMULATED_TEST_ONLY backend on 127.0.0.1:8000
npm run dev      # terminal 2 - the app on 127.0.0.1:5173
```

Point `SIDECKICK_API_TARGET` at the real backend instead of the stub once the
services are running. The interface will then show `backend live` instead of
`backend dev stub`, because that label comes from the backend's own
capabilities response.

---

## 1. The first screen (10 seconds)

Open the app. Three things are true immediately:

- The **companion** is on the left, calm and waiting. It is not a logo - it
  changes with what Sidekick is doing.
- The **task panel** says what Sidekick is ready for. It is the real task, not
  a decorative card.
- The left rail shows the **capability strip**: `backend DEV STUB`,
  `voice.stt LIVE`, `music.play UNCONFIGURED`. With the real backend it reads
  `backend LIVE` and lists the real tools. **That label is the point** - the
  interface never claims more than the backend can do.

## 2. Voice in, real answer out (30 seconds)

Press the microphone button and say:

> "Play a song on Spotify"

You will see the interim transcript in the composer, then the request go out,
then the **decision trace** appear: what was heard, how it was understood,
which model decided, which actions were planned, and what came back.

Then type the same thing instead. **The text path is a first-class fallback,
not a debug mode.**

### If the browser has no speech engine

Open the app in a browser without `SpeechRecognition`, or deny the microphone
permission. The microphone button disables itself, the composer switches to
`text only`, and the reason is stated. Nothing silently fails.

## 3. Watch the decision (30 seconds)

Scroll to the trace and read it out loud:

- **Heard** - your words, and that they came from the microphone.
- **Understood** - the normalized intent, the confidence, whether it was
  ambiguous.
- **Decided** - the provider, the model, the source, and whether a fallback ran.
  If the backend reports `fallback_used: true`, the trace says
  `rule-engine-v1 (fallback)` rather than hiding it.
- **Planned** - every action, its arguments, and whether it needs approval.
- **Acted** - the events with their sequence numbers and real timestamps.
- **Result** - the outcome, the error code, the changed files, the test result
  and the diff.

Click **Raw payload** to show the actual JSON the backend sent, then hide it
again.

## 4. A correction that actually changes the destination (30 seconds)

> "Open YouTube and play a song"

Then, before anything executes:

> "No wait, Spotify"

The backend resolves the correction, the plan shows the corrected destination,
and the log states that the earlier destination was replaced before execution.
The browser only raises the correction signal - the decision engine decides
what it means.

## 5. Multi-action and approval (30 seconds)

> "Play a song on Spotify and then start a chess game"

Two actions, two states, in order.

Then:

> "Delete the playlist on Spotify"

A confirmation card appears with **Yes, do it** / **No, cancel**. Nothing
executes until the answer is bound to that exact action.

## 6. Live progress and a real diff (30 seconds)

> "Write a function that greets the user"

The progress events stream in while the job runs - the events come from the
backend over an event stream, not from a browser timer. When the job finishes,
the result shows the **diff**, the **changed files** and the **test result**
together. If the required tests failed, the panel says `partial - changes were
applied but the required tests failed` and shows the real exit code. It never
looks like a success.

## 7. Movie Buddy - the part that is easy to fake (90 seconds)

**Step 1 - turn it on, without naming a film.** Say:

> "Turn on Movie Buddy."

The interface switches to Movie Buddy and says what it can observe: it reads
the caption track of the video playing in this app, it cannot see other tabs or
streaming services, and it does not analyse the picture.

**Step 2 - play the film.** Press play. The film is *Letter V*, a public-domain
(CC0) short that is bundled with the app, so it plays without depending on a
third-party host. The caption track is the film's own hand-authored English
captions.

**Step 3 - watch the companion stay quiet.** For the first few seconds
nothing happens. That is the point: the companion has a speaking budget of
three remarks a minute, a twelve-second cooldown, and it never talks over a
caption line.

**Step 4 - see a real reaction.** Around **0:02** the narration says
*"Twist the first soft two inch bubble."* The companion reacts to that line and
shows **why**: click **Why did Sidekick react?** and it tells you the rule that
fired and quotes the caption with its timestamp. It also tells you what it
would be holding back for right now.

**Step 5 - ask it a question.** Say:

> "What just happened?"

The answer quotes the captions from the last 45 seconds and says it is reading
the subtitle track. Then ask about a moment with no captions and it says
plainly that it cannot know.

**Step 6 - silence it.** Say:

> "Be quiet for a bit."

The commentary stops immediately and the panel counts down the quiet window.

**Step 7 - bring it back.** Say:

> "Resume Movie Buddy."

**Step 8 - drive the player.** Say "Pause the movie." or "Go back 30 seconds."
and the real media clock moves.

### If the media fails

The interface says the video could not be played and the rest of the product
keeps working. A caption failure disables the companion rather than faking
understanding.

## 8. Music and games stay honest (20 seconds)

Open **Music**: the providers are listed with their real state and the reason
they cannot play. There is no fake player, because there is nothing to play.

Open **Games**: the list comes from the backend. Below it, **Local activities**
holds two games that ship with the client and need no service at all -
Tic-Tac-Toe (with a real minimax opponent, not a random move) and 2048 (with
the real merge rules). Both are marked `local`, so a viewer can tell at a
glance what runs on the device and what runs on a server.

## 9. Interruption (10 seconds)

Ask something and let Sidekick start answering. Press the microphone button
while it is speaking: the speech stops and the microphone opens. That is the
barge-in path, not a mock.

## 10. Disconnect (10 seconds)

Stop the backend. The capability strip switches to `backend disconnected`, the
talk surface shows a recoverable error with a **Retry** button, and the movie
companion keeps working.

---

## What a viewer should take away

- The interface shows the backend's real state, including when that state is
  "not configured" or "simulated".
- The decision is visible: what was heard, what was understood, what was
  chosen, and what happened - with the fallback shown, not hidden.
- The companion events are tied to real media time and real caption cues, and
  the companion explains its own trigger.
- The browser is honest about what it cannot do: no voice engine, no
  microphone, no provider, no backend.
