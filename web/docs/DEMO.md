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
Core/Execution services exist. The interface will then show `backend live`
instead of `backend dev stub`, because that label comes from the backend's own
capabilities response.

## 1. The capability strip (10 seconds)

Look at the left rail before doing anything. It shows exactly what the backend
reports: `voice.stt LIVE`, `voice.tts LIVE`, `intent.resolve SIMULATED`,
`music.play UNCONFIGURED`, and so on. With the stub it says `backend DEV
STUB`. **That label is the point** - the interface never claims more than the
backend can do.

## 2. Voice in, real answer out (30 seconds)

Press the microphone button and say:

> "Play a song on Spotify"

You will see the interim transcript in the composer, then the request go out,
then the action plan appear with the real tool name and arguments.

Then type the same thing instead. **The text path is a first-class fallback,
not a debug mode.**

### If the browser has no speech engine

Open the app in a browser without `SpeechRecognition`, or deny the microphone
permission. The microphone button disables itself, the composer switches to
`text only`, and the reason is stated. Nothing silently fails.

## 3. A correction that actually changes the destination (30 seconds)

> "Open YouTube and play a song"

Then, before anything executes:

> "No wait, Spotify"

The backend resolves the correction, the plan shows the corrected destination,
and the log states that the earlier destination was replaced before execution.
The browser only raises the correction signal - the decision engine decides
what it means.

## 4. Multi-action and confirmation (30 seconds)

> "Play a song on Spotify and then start a chess game"

Two actions, two states, in order.

Then:

> "Delete the playlist on Spotify"

A confirmation card appears with **Yes, do it** / **No, cancel**. Nothing
executes until the answer is bound to that exact action.

## 5. Live progress and a real diff (30 seconds)

> "Write a function that greets the user"

The progress events stream in while the job runs - the events come from the
backend over an event stream, not from a browser timer. When the job finishes,
the patch the backend produced is rendered as a diff with the added and
removed lines coloured.

## 6. The movie companion - the part that is easy to fake (60 seconds)

Open **Movie**.

1. Press play. The film is *Tears of Steel* (Blender Foundation / MPEG,
   CC BY 3.0), streamed from the Internet Archive.
2. Turn on the browser's caption control. The subtitles are the film's
   **official English subtitle file**, committed to the repository and parsed
   in the browser - the same cues that drive the companion.
3. Let it play to about **0:30**. The line *"Why don't you just admit that
   you're freaked out by my robot hand?"* starts at 00:00:30,800 in the
   official track. At that exact moment the companion raises **Robotics
   mentioned**, showing the timestamp, the line, and why it appeared.
4. Scroll the companion panel: the other events are at their own real
   timestamps - **Memory theme** at 0:50, **Closing reflection** at 9:22.
5. Switch to **Brief** mode and replay from 0:00. The companion speaks a short
   line in the gaps between dialogue and never talks over a subtitle line.
6. Switch to **Quiet**. Nothing is spoken and no card is raised.

The companion panel states its own limits: *Subtitle-based understanding - no
visual analysis*. That is true, and it is the difference between this and a
timer that pops up captions every few seconds.

### If the media fails

The interface says the video could not be loaded and the rest of the product
keeps working. A subtitle failure disables companion events rather than
faking understanding.

## 7. Music and games stay honest (20 seconds)

Open **Music**: Spotify and YouTube Music are listed as `not configured`, with
the reason (they need a developer app id and a user token). There is no fake
player, because there is nothing to play.

Open **Games**: the list comes from the backend. With the stub, chess is
`simulated` and the board renders the position the backend reports - the
browser never decides a move.

## 8. Interruption (10 seconds)

Ask something and let Sidekick start answering. Press the microphone button
while it is speaking: the speech stops and the microphone opens. That is the
barge-in path, not a mock.

## 9. Disconnect (10 seconds)

Stop the backend. The capability strip switches to `backend disconnected`, the
talk surface shows a recoverable error with a **Retry** button, and the movie
companion keeps working.

---

## What a viewer should take away

- The interface shows the backend's real state, including when that state is
  "not configured" or "simulated".
- The companion events are tied to real media time and real subtitle cues.
- The browser is honest about what it cannot do: no voice engine, no
  microphone, no provider, no backend.
