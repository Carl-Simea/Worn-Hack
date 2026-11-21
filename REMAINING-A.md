# REMAINING: agent A (backend)

_Last updated 2026-11-21, overnight. Everything below is pushed to origin/main._

## Done
- **Full contract** (`backend/README.md` has the exact shapes): `/health /content /session (write|dictation|compose)
  /session/next /session/result /grade /stroke-match /ink-diff /compose /event /live/state /name /journal /review
  /reset /capture/latest /agent/tools`, plus the pages `/live /mirror /app /app/journal /print/{lang} /glasses` from `/web`.
- **Tutor agent** (observe → evaluate → decide → act) with real tools: `grade_character`, `compare_to_template`,
  `choose_next_item` (per-user mistake memory), `compose_message`, `react`. Every step and its latency show in
  `/live/state.agent_steps`. 14b → 7b hedged fallback, guardrails, and a rule policy if both models are down.
- **3-tier perception** with per-tier latency in `/live/state.latency`.
- **6 languages** (Mandarin, Hindi, Arabic, Russian, Hebrew, Greek). Japanese and ASL are filtered out even if a file returns.
- **Tests:** `uv run pytest` (65 fast, models mocked) and `uv run pytest -m live` (real qwen2.5vl on teammates' handwriting).

## Real-world handwriting eval (teammate notebook photos, `backend/test_data/handwriting`)
Full table: `backend/test_data/eval_results.md` (re-run: `uv run python eval_handwriting.py --live`).

| tier | result | latency |
|---|---|---|
| Ink extraction on full notebook pages | 100% / 100% / 88% of detected ink is real writing (lines, holes, spiral, shadows ignored) | 10–25 ms |
| 1: ink diff (new stroke?) | **18/18**: 0 false strokes under camera shift + rotation, shadow, dimming, recompression; every real stroke caught | ~40 ms |
| 2: stroke match | **96%** final strokes accepted across print / cursive-ish / marker / mixed on 3 real papers; right char beats a confusable one 86% (the misses are all 水 vs 永, which differ by one dot) | ~13 ms (budget 300) |
| 3: vision grade (qwen2.5vl:7b) | **87%** of 76 live grades. Real teammate letters: 94% as photographed, 75% tilted 8° + shadowed, 94% wrong-target rejections. Target scripts on real paper: 86% print, 57% slanted + tilted + shadowed, 100% wrong-char rejections. **0 harsh feedback lines.** | 1–5 s per read (GPU shared tonight) |
| 3 + agent (full /grade: vision, template arbitration, guards) | Target scripts on real paper, print + slanted/tilted/shadowed: **14/14 right letters accepted, 14/14 wrong letters rejected**. Tier 2 settles the vision model's look-alike misreads (ש read as ע, ر as ن, λ as a backslash) and stops it echoing the target (a big X 'read' as 你). | + ~20 ms |

Fixes this test set forced: grading counts capital/small forms and missing Greek accents as correct (with a kind note), an exact read is never failed for style, and LaTeX answers (`\lambda`) are understood (real letters went from 31% to 94%). Ink fixes: lighting-normalized ink (shadows), hysteresis thresholds measured on the photos,
removal of ruled-line spurs, spiral-binding and hole-punch filters, slant search for cursive, and a template-coverage
check (no "done" on a half-written character).

## How to demo (backend side)
1. `ollama serve` (models: `qwen2.5vl:7b`, `qwen2.5:14b`, `qwen2.5:7b`).
2. `cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000`. Wait about 30 s, then
   `curl localhost:8000/health` should list 6 languages and all 3 models under `models.loaded`.
3. Before the judges arrive: `curl -X POST "localhost:8000/reset?journal=true"` for a clean `/live` and journal.
4. Run the iPad on `http://<ip>:8000/live` and the phone app against `http://<ip>:8000`.

## Needs real glasses to verify
- The glasses photo framing: tier 2 and tier 3 were tuned on phone photos of notebook pages plus close-up crops. The M6
  camera's field of view and resolution may need the learner to hold the paper closer. Check one photo in
  `/capture/latest` early.
- The tier-1 thresholds (`NEW_MIN_FRAC = 0.0004` of the frame) assume the character fills a good part of the photo.

## Known limits
- The Xcode license isn't accepted on this Mac, so `/usr/bin/git` fails. Use
  `DEVELOPER_DIR=/Library/Developer/CommandLineTools git ...` or run `sudo xcodebuild -license accept`.
- **Grade latency.** Measured tonight with the iOS Simulator, Xcode and four agent sessions sharing the GPU: 6–8 s per
  `/grade` (vision 1.5–3.5 s, plus the tutor decide step). With the GPU quiet, vision is ~1 s and qwen2.5:14b's short
  decide reply about 1–1.5 s, so expect ~2–3 s. Hard caps: 14b gets 3 s (7b starts in parallel at 1 s) and the whole decide
  step stops at 4.5 s, after which the rule policy decides (logged in `/live`). **At the table, close Xcode and the
  Simulator.** DEMO.md's "about a second" is optimistic; say "a couple of seconds".
- **Hebrew ש** is often read as ע or ב by qwen2.5vl on its own; template arbitration now overturns that when the
  strokes clearly match ש (logged in `/live` as "Template arbitration"). Real glasses photos are still untested.
- **Help me write (compose):** qwen2.5 is weak at Hebrew, Greek and Hindi beyond basic phrases. The backend checks
  every answer independently and refuses rather than teach a wrong phrase. In the test set the check caught 5 of 5
  wrong phrases but also refused some valid requests while the GPU was busy. For the demo, use a lesson phrase or a
  phrase from C's checked phrasebook (`content/phrases/examples.json`, if C adds it), e.g. "thank you, friend" in
  Russian or Mandarin.
- **Slanted Arabic م** matches C's authored template less well than the others (tier-2 hint only; grading is unaffected).
