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
- **Voice-first (11/21 brief):** `content/voice/commands.json` has 20 intents with natural phrasings, common
  mishearings ("Czech" → check, "Indy" → Hindi, "necks" → next), fillers, and aliases for languages, words and
  screens (including the native romanizations: "shalom", "namaste", "xie xie"). `screens.json` gives every glasses
  screen and lesson phase its on-screen "say …" hint (≤ 40 chars, checked), the line spoken on entry and the
  suggestions that "what can I say" reads out. There are 6 How-to-use pages. `tests.json` holds 91 heard → intent cases.
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


## Item checklist (all 30 items, verified 2026-11-21)

`python3 content/tools/verify_items.py` (offline; `--md` prints this table). For each item it checks:
- native text, `chars[]` (the letters joined = the text), romanization, meaning and per-character romanization
- the audio file decodes fully (afconvert) and is at least 0.4 s long
- a stroke file exists for every char
- each stroke file parses, its strokes are in document order, every point is inside the 100×100 box
  (viewBox 0 0 109 109, box 4.5–104.5)
- direction: Arabic/Hebrew joined words run right to left; Hindi multi-glyph files run left to right, with the
  headline last

Mandarin is checked as hanzi-writer JSON (strokes and medians agree). Nothing was missing, so nothing needed generating.
### Mandarin Chinese

| Item | Text | Chars | Rom. | Meaning | Audio | Strokes (files · strokes) | Result |
|---|---|---|---|---|---|---|---|
| hello | 你好 | ✓ 2 | ✓ nǐ hǎo | ✓ | ✓ 1.2 s | 2/2 · 13 | ✅ |
| thank_you | 谢谢 | ✓ 2 | ✓ xièxie | ✓ | ✓ 1.2 s | 2/2 · 24 | ✅ |
| water | 水 | ✓ 1 | ✓ shuǐ | ✓ | ✓ 1.0 s | 1/1 · 4 | ✅ |
| friend | 朋友 | ✓ 2 | ✓ péngyou | ✓ | ✓ 1.2 s | 2/2 · 12 | ✅ |
| one | 一 | ✓ 1 | ✓ yī | ✓ | ✓ 0.9 s | 1/1 · 1 | ✅ |

### Hindi

| Item | Text | Chars | Rom. | Meaning | Audio | Strokes (files · strokes) | Result |
|---|---|---|---|---|---|---|---|
| hello | नमस्ते | ✓ 3 | ✓ namaste | ✓ | ✓ 1.3 s | 3/3 · 12 | ✅ |
| thank_you | धन्यवाद | ✓ 4 | ✓ dhanyavād | ✓ | ✓ 1.6 s | 4/4 · 15 | ✅ |
| water | पानी | ✓ 2 | ✓ pānī | ✓ | ✓ 1.1 s | 2/2 · 9 | ✅ |
| friend | दोस्त | ✓ 2 | ✓ dost | ✓ | ✓ 1.3 s | 2/2 · 10 | ✅ |
| one | एक | ✓ 2 | ✓ ek | ✓ | ✓ 1.0 s | 2/2 · 7 | ✅ |

### Arabic (right to left)

| Item | Text | Chars | Rom. | Meaning | Audio | Strokes (files · strokes) | Result |
|---|---|---|---|---|---|---|---|
| hello | مرحبا | ✓ 6 | ✓ marḥaban | ✓ | ✓ 1.5 s | 6/6 · 9 | ✅ |
| thank_you | شكرا | ✓ 5 | ✓ shukran | ✓ | ✓ 1.4 s | 5/5 · 14 | ✅ |
| water | ماء | ✓ 4 | ✓ māʾ | ✓ | ✓ 1.1 s | 4/4 · 5 | ✅ |
| friend | صديق | ✓ 5 | ✓ ṣadīq | ✓ | ✓ 1.6 s | 5/5 · 15 | ✅ |
| one | واحد | ✓ 5 | ✓ wāḥid | ✓ | ✓ 1.3 s | 5/5 · 7 | ✅ |

### Russian

| Item | Text | Chars | Rom. | Meaning | Audio | Strokes (files · strokes) | Result |
|---|---|---|---|---|---|---|---|
| hello | привет | ✓ 6 | ✓ privet | ✓ | ✓ 1.2 s | 6/6 · 11 | ✅ |
| thank_you | спасибо | ✓ 7 | ✓ spasibo | ✓ | ✓ 1.4 s | 7/7 · 9 | ✅ |
| water | вода | ✓ 4 | ✓ voda | ✓ | ✓ 1.1 s | 4/4 · 9 | ✅ |
| friend | друг | ✓ 4 | ✓ drug | ✓ | ✓ 1.1 s | 4/4 · 9 | ✅ |
| one | один | ✓ 4 | ✓ odin | ✓ | ✓ 1.1 s | 4/4 · 8 | ✅ |

### Hebrew (right to left)

| Item | Text | Chars | Rom. | Meaning | Audio | Strokes (files · strokes) | Result |
|---|---|---|---|---|---|---|---|
| hello | שלום | ✓ 4 | ✓ shalom | ✓ | ✓ 1.1 s | 4/4 · 5 | ✅ |
| thank_you | תודה | ✓ 4 | ✓ toda | ✓ | ✓ 1.0 s | 4/4 · 7 | ✅ |
| water | מים | ✓ 3 | ✓ mayim | ✓ | ✓ 1.1 s | 3/3 · 4 | ✅ |
| friend | חבר | ✓ 3 | ✓ chaver | ✓ | ✓ 1.1 s | 3/3 · 5 | ✅ |
| one | אחד | ✓ 3 | ✓ echad | ✓ | ✓ 1.1 s | 3/3 · 7 | ✅ |

### Greek

| Item | Text | Chars | Rom. | Meaning | Audio | Strokes (files · strokes) | Result |
|---|---|---|---|---|---|---|---|
| hello | γεια σου | ✓ 7 | ✓ yia sou | ✓ | ✓ 1.1 s | 7/7 · 8 | ✅ |
| thank_you | ευχαριστώ | ✓ 9 | ✓ efcharistó | ✓ | ✓ 1.5 s | 9/9 · 13 | ✅ |
| water | νερό | ✓ 4 | ✓ neró | ✓ | ✓ 1.0 s | 4/4 · 5 | ✅ |
| friend | φίλος | ✓ 5 | ✓ fílos | ✓ | ✓ 1.3 s | 5/5 · 8 | ✅ |
| one | ένα | ✓ 3 | ✓ éna | ✓ | ✓ 1.0 s | 3/3 · 5 | ✅ |

0 problems

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
