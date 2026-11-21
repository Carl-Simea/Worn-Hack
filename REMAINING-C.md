# REMAINING: agent C (content + submission docs)

## Done (all pushed to origin/main)

- **6 languages × 5 items** (hello, thank you, water, friend, one): Mandarin, Hindi, Arabic, Russian, Hebrew, Greek.
  Japanese is fully removed. Each item has native text, romanization, meaning, `how` (how the script works),
  `why` (why it's useful), a dictation hint and per-character romanization. Each language has a `hero` greeting.
- **Audio:** 30 clips, one per item, with native macOS voices, a slowed rate and silence padding (shortest is 0.87 s).
- **Stroke order for every character of every item** (116 characters):
  - Mandarin uses standard hanzi-writer-data.
  - Hindi, Arabic (including the 5 joined words), Russian, Hebrew and Greek are hand-authored and labelled
    **"suggested stroke order"**.
  - Every one was checked visually over the real font glyph: `content/review/strokes_*.png`, or live at
    `/static/content/tools/stroke_preview.html`.
- **Write your name:** maps for Devanagari, Arabic, Cyrillic, Hebrew and Greek. Every example rebuilds from its
  sound keys. `names/examples.json` (10 names in all 5 scripts) lets `/name` answer them instantly, offline.
- **Voice-first (11/21 brief):** `content/voice/commands.json` has 18 intents with natural phrasings, common
  mishearings ("Czech" → check, "Indy" → Hindi, "necks" → next), fillers, and aliases for languages, words and
  screens (including the native romanizations: "shalom", "namaste", "xie xie"). `screens.json` gives every glasses
  screen and lesson phase its on-screen "say …" hint (≤ 40 chars, checked), the line spoken on entry and the
  suggestions that "what can I say" reads out. There are 6 How-to-use pages. `tests.json` holds 74 heard → intent cases.
  `content/tools/voice_match.py` is the reference matcher (0 failing); D ports it to JS for the glasses, and A
  can import it for `POST /voice`. Regenerate with `python3 content/tools/make_voice.py`.
  Screen ids agreed with D: home, learn, words, lesson (watch|your_turn|check|result), name, compose, daily5,
  journal, howto.
- **Reactions + milestones + 9 synthesized sound effects** (CC0, made here).
- **Docs:** `DEMO.md` (60-second script, setup checklist, backup plan), `SUBMISSION.md`, `content/REVIEW.md`,
  `content/README.md` and `BUGS.md`.
- **Verified end to end** against the latest backend: `check_content.py` gives 6 languages, 30 items, 116 sessions,
  0 problems. `/live` and `/app` render the content, including RTL Hebrew and Arabic, the Hindi conjuncts and the
  per-character romanization.

## Needs people in the morning (not code)

1. **Native-speaker check:** walk `content/REVIEW.md` with anyone at the venue who speaks Hindi, Arabic, Russian,
   Hebrew, Greek or Mandarin. Check the text, romanization, audio and the suggested stroke order. If something is
   wrong and there's no time to fix it, cut that item from `content/tools/make_content.py` and rerun it.
2. **Team names:** fill the `Team:` line in `SUBMISSION.md` before 2:00pm.
3. **Listen once** to `content/sfx/*.wav` and a few audio clips on the real speaker. They're synthesized, and I
   checked the waveforms (no clipping or silence) but couldn't hear them.

## Needs real hardware to verify

- **Voice in the real room on the M6 mic.** The aliases are guesses at typical recognizer mistakes, not measured on
  the glasses. Whoever tests: note each misheard phrase (what was said → what `heard` came back) and add it to
  `content/tools/make_voice.py`. DEMO.md and SUBMISSION.md now describe the voice-first flow. If /voice isn't
  working by 1:30pm, switch the demo back to phone-driven (the old script is in git: `git show 77a0abb:DEMO.md`).
- Button mapping confirmed with D: press = next / open the highlighted item, hold = check (outside a lesson: How to use), double tap = back. How-to-use and DEMO.md match.
- Stroke animations and RTL text on the actual glasses display (black = see-through, small font sizes).
- Whether the audio's lead-in silence is enough to avoid clipping on the glasses or Bluetooth speaker.
- Tier-2 matching of real handwriting against the suggested templates. A re-ran it after the Arabic م fix; other
  hand-authored letters matched 70–100 on real paper.

## Exact steps (before the demo)

```
cd ~/worn && git pull --rebase origin main
cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000      # in its own terminal
python3 content/tools/check_content.py http://127.0.0.1:8000          # expect "0 problems" (changes the session)
curl -X POST localhost:8000/reset                                      # clean slate for the demo
open http://127.0.0.1:8000/static/content/tools/stroke_preview.html     # eyeball the strokes once
```
Then follow `DEMO.md`.

## Open items for others (in BUGS.md)
- B: none open. #5 (/app at 390 px) was a headless-Chrome capture artifact (B checked a real 390 px viewport), and B
  fixed #7 (the Greek word gap).
- D: the rewritten iOS app no longer follows a session started from another device (BUGS #9). Not demo-blocking.
- iOS Simulator check (iPhone 18 Pro Max, origin/main): builds, connects, loads all content files, and the home
  screen shows all six heroes and script names.
