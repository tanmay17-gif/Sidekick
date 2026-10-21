# Demo walkthrough - Sidekick browser client

A short, honest script for demonstrating the product. Every step below shows
something the interface really did - nothing is scripted animation.

## Before you start

```bash
cd web
npm install
npm run stub     # terminal 1 - SIMULATED_TEST_ONLY backend on 127.0.0.1:8000
npm run dev      # terminal 2 - the app on 127.0.0.1:5173
```

Point `SIDECKICK_API_TARGET` at the real backend instead of the stub once the
services are running. The badge in the top right then reads `BACKEND LIVE`
instead of `DEV STUB`, because that label comes from the backend's own
capabilities response.

Sidekick has **two interfaces and one session**:

- **Ask Sidekick** and **Movie Buddy** are Interface A - the conversational
  surface you talk to.
- **Control room** is Interface B - the developer view of the same work.

---

## 1. Interface A - the first screen (10 seconds)

Open the app. Three things are true immediately:

- The **companion** is large and centred, calm and waiting. It is not a logo -
  it changes with what Sidekick is doing.
- The **suggestions** are the four things that actually work.
- The top right shows the **backend's own state** - `DEV STUB` with the stub,
  `BACKEND LIVE` with the real core. **That label is the point**: the interface
  never claims more than the backend can do.

## 2. Voice in, real answer out (30 seconds)

Press the microphone button and say:

> "Play a song on Spotify"

The interim transcript appears in the composer, the request goes out, and the
answer comes back with the action card the backend really produced.

Then type the same thing instead. **The text path is a first-class fallback,
not a debug mode.**

### If the browser has no speech engine

Open the app in a browser without `SpeechRecognition`, or deny the microphone
permission. The microphone button disables itself, the composer switches to
`text only`, and the reason is stated. Nothing silently fails.

## 3. Interface B - the same request, seen from underneath (30 seconds)

Ask something, then switch to **Control room**. You will see:

- the **architecture diagram**, with each component marked `CONNECTED`, `IDLE`,
  `UNCONFIGURED` or `UNAVAILABLE` according to what the backend actually
  reported - the execution node says `REAL` only when an adapter says so;
- the **request inspector** with the real request id, session id, intent,
  confidence, model, source, risk and status;
- the **action plan** with the real tool, its arguments, and a *Cancel action*
  or *Approve* button when the action is in a state that allows it;
- the **capability health** table with the true status of every tool.

The raw response payload is one click away.

## 4. A correction that actually changes the destination (30 seconds)

> "Open YouTube and play a song"

Then, before anything executes:

> "No wait, Spotify"

The backend resolves the correction, the plan shows the corrected destination,
and the control room's timeline records *"Correction detected - the earlier
destination was replaced before execution"*. The browser only raises the
signal; the decision engine decides what it means.

## 5. Multi-action and approval (30 seconds)

> "Play a song on Spotify and then start a chess game"

Two actions, two states, in order.

Then:

> "Delete the playlist on Spotify"

A confirmation card appears with **Yes, do it** / **No, cancel**. Nothing
executes until the answer is bound to that exact action.

## 6. Movie Buddy (90 seconds)

**Step 1 - turn it on, without naming a film.** Say:

> "Turn on Movie Buddy."

The interface switches to the movie surface and says what it can observe: it
reads the caption track of the video playing in this app, it cannot see other
tabs or streaming services, and it does not analyse the picture.

**Step 2 - play the film.** Press play. The film is *Duck and Cover* (1951), a
U.S. Federal Civil Defense Administration film - **public domain**, bundled
with the app so it never depends on a third-party host. The caption track is
the film's own narration.

**Step 3 - watch the companion stay quiet.** For the first seconds nothing
happens. That is the point: the companion has a speaking budget of three
remarks a minute, a twelve-second cooldown, and it never talks over a caption
line.

**Step 4 - see a real reaction.** Around **0:34** the narration says
*"Meet all these nice people. Bert the Turtle."* The companion reacts, and
click **Why did Sidekick react?** to see the rule that fired and the caption
line with its timestamp.

**Step 5 - ask it a question.** Say:

> "What just happened?"

The answer quotes the captions from the last 45 seconds and says it is reading
the subtitle track. Ask about a moment with no captions and it says plainly
that it cannot know.

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

## 7. Interruption (10 seconds)

Ask something and let Sidekick start answering. Press the microphone button
while it is speaking: the speech stops and the microphone opens. That is the
barge-in path, not a mock.

## 8. Disconnect (10 seconds)

Stop the backend. The badge switches to `OFFLINE`, the conversational surface
shows a recoverable error with a **Retry** button, and the movie companion
keeps working.

---

## What a viewer should take away

- The interface shows the backend's real state, including when that state is
  "not configured" or "simulated".
- The two interfaces are two views of **one** session: what you asked in one
  is the same request, the same action and the same ids in the other.
- The companion events are tied to real media time and real caption cues, and
  the companion explains its own trigger.
- The browser is honest about what it cannot do: no voice engine, no
  microphone, no provider, no backend.
