# web/ (owner: agent B)

Everything people see besides the iPhone app: the judge screen, the glasses display, the learner app on the web,
the handwriting journal and printable worksheets. Plain HTML, CSS and JS (no build step, no framework), served by
the backend. Every page polls the backend, so the phone, the glasses and these pages always show the same lesson.

| URL | File | What it is |
|---|---|---|
| `/live` (also `/mirror`) | `live.html` | **Judge screen** for an iPad or a big monitor, readable from 2 m. Left: exactly what the glasses show (same strokes, "stroke 3 of 7"). Middle: the latest photo of the paper. Right ("Scribi", the voice tutor inside Worn): score, feedback, Scribi's reaction, a big check and rainbow confetti. Bottom: the agent's steps live (tool, model, ms) and a timeline. Header: latency chips (INK = tier 1, STROKE = tier 2, VISION = tier 3, SCRIBI = decide), listening indicator, glasses dot, a "Demo mode" tag when the iPhone is in demo mode, and a milestone banner. |
| `/glasses` | `glasses.html` | The 640×480 glasses display: black = see-through, bright strokes, result overlay, confetti, sounds. Add `?sound=1` so sounds play without a tap. |
| `/app` | `app.html` | The learner flow on the web (backup demo + preview): scripts with the script as hero, practice with the stroke animation and audio, dictation, **Help me write**, **Write your name**, **Daily 5**, and **Check with phone camera**. Shows a "continue here" banner when a lesson starts on another device. |
| `/app/journal` | `journal.html` | Every graded photo, grouped by character: day one next to the latest, every try in between. |
| `/print/{lang}` | `print.html` | Printable A4 worksheets: stroke-by-stroke steps, a solid model, a faint one to trace, then empty 3 cm boxes (sized for the glasses camera). Print at 100%. |
| `/static/web/stroke-test.html` | `stroke-test.html` | Pre-demo check: animates every lesson character in all six scripts and says which data each one uses. Doesn't touch the session. |
| `/static/web/phone.html` | `phone.html` | Old backup picker, now a redirect to `/app`. |

Shared code: `worn.css` (design system: paper and ink, one ultramarine accent, Newsreader + Inter, Noto for every script,
dark mode), `worn-ink.js` (stroke renderer for hanzi-writer-data and the centerline SVGs in `content/strokes`, with
loop, follow-the-glasses sync, static partial and word-gap helpers), `worn-confetti.js`, `worn-sfx.js` (C's
`content/sfx` sounds picked by `content/reactions.json`).

Fonts: Inter and Newsreader are self-hosted in `web/fonts/` (`fonts.css`), so the brand survives a venue network
without internet. The Noto script faces come from Google Fonts and fall back to the system's fonts offline.

**Voice-first (`/voice`, `/app-state`):** `/live` has a voice bar under the header. It shows where the wearer is
(breadcrumb), what they said, the command Worn understood, its reply (with latency) and the "Say …" hint, read from
`GET /app-state` every 500 ms. It stays hidden on a backend without that endpoint. `/app` has a mic button on every screen
with that screen's hint: it records 16 kHz WAV locally and sends it to `POST /voice`, then acts on the reply (navigate,
next/previous/repeat, start a word, help me write, write my name) and plays `say_url`. `/app#/help` is the "What can I say"
page: tap a command or type one (sent as `text`). `worn-voice.js` holds the recorder and the command list. In the console,
`wornSay("learn Greek")` runs the same path.

**Real glasses mirror on `/live`:** with the M6 plugged into the laptop over USB, the left panel switches to
"LIVE: what the wearer sees", an MJPEG stream of the actual display (`GET /glasses/screen.mjpg`, `adb exec-out screencap`,
about 4–5 fps; `/glasses/screen/status` says whether it's real). Unplugged, it falls back to the drawn view within 3 s.
`/live?screen=0` turns the mirror off. `WORN_ADB_SERIAL` picks a device if several are attached.

Query params on every page: `?api=http://IP:8000` (talk to another server), `?theme=dark|light`.

## Dev tools (`web/dev/`)

    python3 web/dev/mock_server.py --port 8090              # stand-in backend with a demo loop (same JSON as A's)
    uv run --with playwright python web/dev/shoot.py http://127.0.0.1:8090 /live /app --out screenshots/web
    uv run --with playwright --with pillow python web/dev/e2e_app.py http://127.0.0.1:8092   # clicks through /app
    uv run --with pillow python web/dev/sim_glasses.py http://127.0.0.1:8000 --lang mandarin --item hello [--wrong]

- `shoot.py`: phone (390), iPad (1180) and laptop (1440) screenshots. It fails on any console error or sideways scroll.
- `e2e_app.py`: starts a lesson, checks the stroke animation, grades a photo, Next, dictation, compose, name, Daily 5,
  and that `/live` follows. Passes against the mock and the real backend. **It starts lessons, so never run it during the demo.**
- `sim_glasses.py`: plays the iPhone + glasses against a real backend (events, `/stroke-match`, `/grade`, confetti,
  `/session/next`) so `/live` can be shown without hardware. `--wrong` writes an X first to show the retry path.

Screenshots of every page at all sizes, light and dark: `screenshots/web/`.

Credits: stroke data from hanzi-writer-data (Make Me a Hanzi, Arphic license) and C's hand-authored suggested order
for the alphabets. Fonts: Noto (OFL), Newsreader, Inter (Google Fonts).
