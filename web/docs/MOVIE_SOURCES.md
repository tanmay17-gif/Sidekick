# Movie sources and rights evidence

The movie companion plays openly licensed material. This file records the
**exact copy** used, where it came from, what the rights are, and what is known
to be wrong with it. Nothing here is a blanket claim about a collection.

---

## `letter-v` - the default film

| Field | Value |
|---|---|
| Title | *Letter V* |
| Source | Internet Archive item `LetterV` - `https://archive.org/details/LetterV` |
| Files used | `LetterVDvd.mp4` (15,619,434 bytes) and `CaptionsLetterVBalloonTwistingAbc.srt` (2,695 bytes) |
| Item `licenseurl` | `http://creativecommons.org/publicdomain/zero/1.0/` (CC0 1.0) |
| Item `collection` | `opensource_movies`, `community` |
| Item `creator` | `Langerman www.fewdoit.com` |
| Item `description` | "Balloon twisting de vA-deo instruction by Langerman www.fewdoit.com (author reserved no rights) public domain dedication." |
| Item `runtime` | `2:29` (`ia_orig__runtime`: "2 minutes 29 seconds") |
| Item `sound` | `sound` |
| Captions | Hand-authored English subtitle file, 45 cues covering 00:00:01 - 00:02:29, i.e. the whole film |

### Why this copy

The item's own rights metadata records a **public domain dedication by the
creator of this specific copy** ("author reserved no rights) public domain
dedication"), published under **CC0 1.0**. CC0 permits redistribution, so the
file is bundled in this repository rather than only streamed. The caption file
ships with the item and was authored by hand - it is not an automatic
transcription - and it covers the entire runtime, so every moment of the film
has a real timed cue.

The captions are the grounding for the companion. They read as a spoken
procedure ("Inflate a balloon leaving a four inch flat tail.", "Twist the
first soft two inch bubble.", "Lock both ends of the first bubble in one lock
twist.") and mark sound effects in brackets ("(birds chirping)"), which is
what lets the companion make a comment that is actually about what was said.

### What is bundled

```
web/public/media/letter-v/letter-v.mp4    15.6 MB   H.264 + AAC, faststart
web/public/media/letter-v/letter-v.webm    3.1 MB   VP9 + Opus (transcoded)
web/public/media/letter-v/letter-v.srt     2.7 KB   hand-authored captions
```

The WebM is the **same film**, transcoded locally from the bundled MP4 with
FFmpeg 7.1 (`libvpx-vp9`, `libopus`). It exists because the Chromium build
that ships with Playwright has **no H.264 decoder** (`canPlayType` returns the
empty string for `avc1`), so without it the automated browser tests could not
play the film at all. The `<video>` element offers both and the browser takes
the first one it can decode; Chrome and Edge take the MP4, the codec-limited
Chromium takes the WebM. Both carries the same audio and the same picture.

### Attribution

The film is credited in the interface as *"Letter V - public domain dedication
(CC0 1.0), Internet Archive item LetterV"*. CC0 does not require attribution,
so this is a courtesy rather than an obligation.

### Honest caveats

- The item is a **community** upload on the Internet Archive, not a curated
  institutional collection. The creator credit in the metadata is
  "Langerman www.fewdoit.com" and the description describes a de novo
  instructional video. **This client does not claim the file is Norman
  McLaren's 1955 NFB short of the same name**, because that has not been
  verified for this copy.
- The file was uploaded in 2012 and the archive's copy of it is what is
  bundled. The archive's own malware curation note is attached to the item.
- The bundled MP4 is byte-identical to the archive's `LetterVDvd.mp4`; the
  bundled WebM is a derivative of it.

---

## `tears-of-steel` - the second film

| Field | Value |
|---|---|
| Title | *Tears of Steel* (2012) |
| Source | Internet Archive item `Tears-of-Steel` - `https://archive.org/details/Tears-of-Steel` |
| Video | `tears_of_steel_720p.mp4` (76,435,802 bytes), faststart H.264, `Accept-Ranges: bytes` |
| Captions | `web/public/media/tears-of-steel/TOS-en.srt` - the **official** English subtitle file from `download.blender.org/demo/movies/ToS/subtitles/TOS-en.srt` (4,764 bytes, 76 cues, 00:00:23 - 00:09:27) |
| Rights | CC BY 3.0 - *Tears of Steel* is a Blender Foundation / MPEG open movie |

This one is **streamed, not bundled**: the file is 76 MB and the Internet
Archive serves it with range support, so the browser fetches only what it
plays. The caption file is bundled because `download.blender.org` does not send
a CORS header, so the browser cannot fetch it directly.

### Negative results worth recording

These were checked and rejected, so nobody repeats the search:

| Source | Result |
|---|---|
| `download.blender.org/.../TOS-en.srt` | Reachable, but **no `Access-Control-Allow-Origin`** header, so a browser cannot fetch it. This is why the file is bundled. |
| `media.w3.org/2010/05/sintel/trailer.mp4`, `.../bunny/trailer.mp4` | Reachable, but **no matching subtitle track** at any of the usual paths, and **no CORS header**. |
| `media.w3.org/2010/05/video/movie_300.mp4` | Reachable, no matching `.vtt`, no CORS header. |
| `download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov` | 372 MB, and the `moov` atom is at the **end** of the file, so the browser must fetch the tail before it can start. The Internet Archive MP4 derivative is 5x smaller and faststart. |
| `www.loc.gov` public-domain film collection | **Unreachable from this environment** - the site is behind a Cloudflare bot challenge that the CLI and the automated browser both fail. The Library of Congress collection was therefore *not* used, and no Library of Congress specific claim is made anywhere in this project. |

---

## What the companion may and may not observe

**May**: the caption track of the video playing in this app, the real playback
clock, play/pause/seek/buffering/end-of-film state, the playback rate, and
what the user explicitly asks for.

**May not**: other browser tabs, streaming services (Netflix, Prime Video,
YouTube), desktop applications, system audio, or the picture itself. This build
has **no visual analysis** - the interface says so on the Movie Buddy surface
and in every answer the companion gives.

A user can also open a video file from their own machine (`Open a file`).
Such a file plays in the same player but has **no caption track**, so the
companion has nothing to ground a comment in and says so rather than inventing
one.

---

## Reproducing the checks

```bash
# the bundled film really plays and the captions follow the media clock
npx playwright test tests/e2e/app.spec.ts -g "really plays the bundled film"

# the codec situation, for the record
#   chrome/edge  -> MP4 (H.264)
#   playwright chromium -> WebM (VP9)
```
