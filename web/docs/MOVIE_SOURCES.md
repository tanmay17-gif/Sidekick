# Movie sources and rights evidence

The movie companion plays openly licensed material. This file records the
**exact copy** used, where it came from, what the rights are, and what is known
to be wrong with it. Nothing here is a blanket claim about a collection.

---

## `duck-and-cover` - the default film

| Field | Value |
|---|---|
| Title | *Duck and Cover* (1951) |
| Source | Internet Archive item `DuckandC1951` - `https://archive.org/details/DuckandC1951` |
| Collection | `prelinger` (Prelinger Archives), `community` |
| Sponsor | U.S. Federal Civil Defense Administration |
| Producer | Archer Productions, Inc. |
| Item `licenseurl` | `http://creativecommons.org/licenses/publicdomain/` |
| Item `description` | "Selected for the 2004 National Film Registry of 'culturally, historically and aesthetically significant' motion pictures. Famous Civil Defense film for children in which Bert the Turtle shows what to do in case of atomic attack." |
| Item `runtime` | `9:15` |
| Item `sound` | `sound` |
| Files used | `DuckandC1951_512kb.mp4` (39,240,901 bytes) and `DuckandC1951.asr.srt` (10,810 bytes) |

### Why this copy

This is the strongest rights position of anything the team could reach:

- it is a **work of the United States government** - produced by the U.S.
  Federal Civil Defense Administration - and therefore not subject to U.S.
  copyright at all;
- the Internet Archive records the item under the **`prelinger`** collection,
  which is dedicated to public-domain industrial and educational film, and
  marks the item `publicdomain`;
- the film's own item description records that it was **selected for the
  National Film Registry**, which is the Library of Congress's own record of
  culturally significant films - a citation the project can point at.

It is also, unambiguously, the most recognisable short in the public domain:
**Bert the Turtle** is a piece of shared popular culture in the United States,
and the film contains the mushroom-cloud sequence everyone remembers.

### The clip

The bundled asset is a **2:30 clip** of the film's first three minutes
(source `00:00:32` - `00:03:02`), cut locally with FFmpeg 7.1. It contains:

| Clip time | What is on screen / said |
|---|---|
| 00:00:10 | **Bert the Turtle** introduces himself |
| 00:00:40 | the **atomic flash and the mushroom cloud** |
| 00:01:10 | the narrator explains what the flash would do to you |
| 00:01:50 | "first duck, and then cover" - the lesson the film is remembered for |

The clip is short enough for a hackathon presentation, it has a clear dramatic
arc, and it has continuous narration - which is what lets the companion be
grounded in real dialogue rather than in nothing.

### The picture

The archive has two different transfers and they are not the same picture:

| File | Dimensions | Shape |
|---|---|---|
| `DuckandC1951.mp4` | 368 x 480 | **portrait** (the 1951 television release) |
| `DuckandC1951_512kb.mp4` | 320 x 240 | **landscape 4:3** (the complete frame) |

The clip is cut from the **landscape** transfer, because it shows the whole
composition - Bert is not cropped - and the player can show it without
pillarboxing. The transfer is 320x240, so the bundled clip is upscaled to
640x480 with a Lanczos filter and a mild unsharp mask; it is still a 1951
television print and it looks like one. That is stated rather than hidden.

### The captions

The archive ships an **automatic transcription** of the narration
(`DuckandC1951.asr.srt`, 117 cues over the full 9:06). For the bundled clip:

- the **timings are the archive file's own**, unchanged and rebased to the
  clip's zero;
- the **wording was corrected by hand** where the machine transcription was
  obviously wrong, and nothing else was changed. The corrections are:

| Transcription | Corrected to |
|---|---|
| "and cover this is an official civil defense film" | "Duck and Cover. This is an official civil defense film" (the film title) |
| "meet all these nice people play a ride" | "Meet all these nice people. Bert the Turtle" (the character) |
| "You see Byrd is a very very careful fella" | "You see, Bert is a very, very careful fella" |
| "and has danger" | "and he's in danger" |
| "I don't feel it can be dangerous to sometimes cause bad accidents" | "We know it can be dangerous, and sometimes it causes bad accidents" |
| "like bird" / "like birds the turtles" | "like Bert" / "like Bert the Turtle" |
| "But when I get ready" | "But when it does" |
| "and did not know what to do" | "and do not know what to do" |

No line was invented and no timing was moved. The result is 38 cues covering
the whole clip. The original archive file is still downloadable from the item
page, and the corrected track is the one that ships.

### What is bundled

```
web/public/media/duck-and-cover/duck-and-cover.mp4    21.2 MB   H.264 + AAC, faststart
web/public/media/duck-and-cover/duck-and-cover.webm    8.2 MB   VP9 + Opus, transcoded
web/public/media/duck-and-cover/duck-and-cover.srt     2.5 KB   38 cues, real timings
```

The WebM is the **same clip**, transcoded locally from the bundled MP4 with
FFmpeg 7.1 (`libvpx-vp9`, `libopus`). It exists because the Chromium build
that ships with Playwright has **no H.264 decoder** - `canPlayType` returns
the empty string for `avc1` - so without it the automated browser tests could
not play the film at all. The `<video>` element offers both and the browser
takes the first one it can decode: Chrome and Edge take the MP4, the
codec-limited Chromium takes the WebM. Both carry the same picture and the same
audio.

### Attribution

The film is credited in the interface as *"Duck and Cover (1951) - U.S. Federal
Civil Defense Administration, produced by Archer Productions; public domain,
Prelinger Archives on the Internet Archive"*. Public-domain status does not
require attribution, so this is a courtesy rather than an obligation.

### Honest caveats

- The bundled MP4 is a **transcode**, not the archive's own file: the source
  `DuckandC1951_512kb.mp4` was cut to the clip window, upscaled to 640x480 and
  re-encoded. The archive's `DuckandC1951.mp4` is a different transfer
  (portrait) and was deliberately not used.
- The bundled WebM is a second transcode of that transcode.
- The 320x240 source transfer is soft. The clip is presented as a 1951
  television print, which is what it is.
- "National Film Registry" is a Library of Congress selection of culturally
  significant films. It is **not** a determination that a particular copy is
  free of copyright - which is why this project relies on the film's US
  government authorship instead.

---

## `letter-v` - the second film

| Field | Value |
|---|---|
| Title | *Letter V* |
| Source | Internet Archive item `LetterV` - `https://archive.org/details/LetterV` |
| Files used | `LetterVDvd.mp4` and `CaptionsLetterVBalloonTwistingAbc.srt` (45 cues, 00:00:01 - 00:02:29 - the whole film) |
| Item `licenseurl` | `http://creativecommons.org/publicdomain/zero/1.0/` (CC0 1.0) |
| Item `creator` | `Langerman www.fewdoit.com` |
| Item `description` | "Balloon twisting de vA-deo instruction by Langerman www.fewdoit.com (author reserved no rights) public domain dedication." |
| Item `runtime` | `2:29` |

A **public domain dedication by the creator of this specific copy**, published
under CC0, with a hand-authored caption track that covers the entire film. It
is bundled so the feature is demonstrably **not** hard-coded to one film.

Caveat: the item is a community upload. This client does **not** claim the
file is Norman McLaren's 1955 NFB short of the same name, because that has not
been verified for this copy.

## `tears-of-steel` - the third film

| Field | Value |
|---|---|
| Title | *Tears of Steel* (2012) |
| Source | Internet Archive item `Tears-of-Steel` - `https://archive.org/details/Tears-of-Steel` |
| Video | `tears_of_steel_720p.mp4` (76,435,802 bytes), faststart H.264, `Accept-Ranges: bytes` |
| Captions | `web/public/media/tears-of-steel/TOS-en.srt` - the **official** English subtitle file from `download.blender.org/demo/movies/ToS/subtitles/TOS-en.srt` (76 cues) |
| Rights | CC BY 3.0 - *Tears of Steel* is a Blender Foundation / MPEG open movie |

Streamed, not bundled: the file is 76 MB and the Internet Archive serves it
with range support. The caption file is bundled because `download.blender.org`
does not send a CORS header, so the browser cannot fetch it directly.

---

## Negative results worth recording

These were checked and rejected, so nobody repeats the search:

| Source | Result |
|---|---|
| `www.loc.gov` public-domain film collection | **Unreachable from this environment** - the site is behind a Cloudflare bot challenge that both the CLI and the automated browser fail to pass. It was retried in milestone 3. No Library of Congress specific claim is made anywhere in this project. |
| `media.w3.org/2010/05/...` | The Sintel and Bunny trailers are reachable but there is **no matching subtitle track** at any of the usual paths, and **no CORS header**. |
| `media.w3.org/2010/05/video/movie_300.mp4` | Reachable, no matching `.vtt`, no CORS header. |
| `download.blender.org/.../tears_of_steel_720p.mov` | 372 MB, and the `moov` atom is at the **end** of the file, so the browser must fetch the tail before it can start. The Internet Archive MP4 derivative is 5x smaller and faststart. |
| `download.blender.org/.../TOS-en.srt` | Reachable, but **no `Access-Control-Allow-Origin`** header, so a browser cannot fetch it. That is why the file is bundled. |
| `archive.org` "public domain + SubRip" search | 22,824 hits, but almost all are modern community uploads of unknown rights. The two usable ones were *Duck and Cover* and *Letter V*. |

---

## What the companion may and may not observe

**May**: the caption track of the video playing in this app, the real playback
clock, play/pause/seek/buffering/end-of-film state, the playback rate, and
what the user explicitly asks for.

**May not**: other browser tabs, streaming services (Netflix, Prime Video,
YouTube), desktop applications, system audio, or the picture itself. This
build has **no visual analysis** - the interface says so on the Movie Buddy
surface and in every answer the companion gives.

A user can also open a video file from their own machine (`Open a video`) and
attach a subtitle file to it (`Load subtitles`, `.srt` or `.vtt`). The subtitle
file is parsed **in the browser** and is never uploaded. With those captions
the companion has real cues to read and can remark on them.

If the loaded captions stop long before the film ends, the interface reports
that the subtitles may not match that copy of the film, because a remark based
on the wrong captions would be worse than no remark at all. A video with no
caption track gets a clear notice that the companion has nothing to read,
together with the "load subtitles" affordance.

---

## Reproducing the checks

```bash
# the bundled film really plays and the captions follow the media clock
npx playwright test tests/e2e/app.spec.ts -g "really plays the bundled film"

# the companion remarks in the gap after a line and explains why
npx playwright test tests/e2e/app.spec.ts -g "remarks in the gap"

# the codec situation, for the record
#   chrome / edge          -> MP4 (H.264)
#   playwright chromium     -> WebM (VP9)
```
