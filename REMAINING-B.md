# REMAINING-B (agent B: /web)

## Done and verified
- **`/live` (also `/mirror`)**, the judge screen. The glasses view uses the same strokes as the glasses ("stroke 3 of 7", synced
  from `/live/state`). It also shows the latest paper photo, the score with a count-up and a check, the feedback and reaction,
  and rainbow confetti on a pass or a confetti event. Below that: the agent's steps (tool, model, ms), a timeline that reads
  every iOS event, latency chips INK/STROKE/VISION/TUTOR, a listening pill with the last thing heard, the glasses dot, a
  demo-mode tag and a milestone banner. It polls every 500 ms with `?since=` and only re-renders on change.
- **`/glasses`**: 640×480, black, the same renderer, result overlay, confetti, C's sfx (`?sound=1` on the device).
- **`/app`**: scripts, practice (follows whatever lesson is live, so it hands off with the iPhone), dictation, Help me write
  (with one-tap ideas), Write your name (5 scripts, tap to trace), Daily 5, phone-camera grading, Prev/Next, keys
  (space, ←/→, h). It never double-advances: a 409 from `/session/next` means the iPhone already moved on.
- **`/app/journal`**: day one next to the latest photo for each character, every try in between, filter by script.
- **`/print/{lang}`**: A4 worksheets, one page per sheet (checked by PDF page count): stroke-by-stroke steps, a model,
  a trace, empty 3 cm boxes. Right-to-left rows for Arabic and Hebrew.
- **All 6 scripts animate** (`/static/web/stroke-test.html`): Mandarin in true order (hanzi-writer-data), the
  others in C's suggested order, plus Arabic joined words.
- Checks: `web/dev/e2e_app.py` 9/9 passing with 0 console errors against the mock **and** A's real backend (a real
  qwen2.5vl read of 你 scored 90). `web/dev/shoot.py` reports no console errors and no sideways scroll at 390/1180/1440 px.
  Separately, 320–768 px in light and dark were checked for overflow. Screenshots of everything are in `screenshots/web/` (light + dark).
- Whole system: `web/dev/sim_glasses.py` plays the iPhone + glasses against the real API. `/glasses`, `/app` and `/live`
  stayed in sync through a retry and a pass, with no console errors.

## How to demo (no code)
1. Backend running (see DEMO.md). iPad: `http://<laptop-ip>:8000/live`, landscape, full screen.
2. Start a lesson on the iPhone (or on `/app`). The glasses and `/live` follow; write on paper; the check and confetti
   appear on both.
3. Backups: `/app` on any phone (same flow, **Check with phone camera**). If nothing drives the glasses:
   `uv run --with pillow python web/dev/sim_glasses.py http://127.0.0.1:8000 --lang mandarin --item hello`.
4. Before the demo, `curl -X POST 'localhost:8000/reset?journal=true'` and never run e2e_app.py or sim_glasses.py while
   presenting (they start lessons).

## Needs real hardware to verify
- How the iPhone app renders on the glasses (D). `/glasses` is ready if the glasses (or the phone mirror) load a web
  page. Use `?sound=1` there, because browsers block sound without a tap.
- `/live` with the real iPhone's events: I tested D's event names from the Swift source and A's handlers, not a live phone.
- Printed worksheet under the real glasses camera (3 cm boxes, thick marker): not tried on paper yet.

## Known limits
- Fonts come from Google Fonts. Without internet, pages fall back to system fonts (still readable; stroke data is
  local, so the animations don't change).
- `sim_glasses.py` draws Greek in Helvetica, so its γ photos look like "Y" and fail grading. That's a test-tool limit only.
  I also asked C to give the γ stroke file its descender, because the current one teaches a "Y".
- I couldn't run the iOS simulator: Xcode's license isn't accepted on this Mac (BUGS.md #8). git works via
  `/Library/Developer/CommandLineTools/usr/bin/git`.
