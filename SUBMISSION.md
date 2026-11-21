# Worn

**Wear it. Write it.** A smart-glasses tutor that teaches English speakers to **write**, on real paper, and say
words in six languages that don't use the Latin alphabet.

- **Event:** Worn Smart Glasses Hackathon · **Track 02: Seamless Handoff**
- **Team:** _add names before submitting_
- **Prior work:** none. Everything was built at this event.

## The problem

Apps teach you to *recognize* 你好 or مرحبا by tapping multiple choice. Almost none teach you to *write* it,
and writing by hand is what makes a script stick. But a phone tutor means looking down at the screen, then at the
paper, then back again, and it can't see your handwriting. So people stall at the first wall: a new script.

## What Worn does

1. **Pick on the phone.** Choose a language and a word (hello, thank you, water, friend, one) or your own name.
2. **Hand off to the glasses.** The glasses show the next character stroke by stroke, with numbered strokes,
   pronunciation audio, romanization and meaning, while your hands stay free for pen and paper.
3. **Write it on real paper.** Tap the glasses: they take a photo and grade it in about a second. You get a check
   and a goofy reaction ("Chef's kiss!"), or one specific fix ("add the dot under the letter"), spoken aloud.
4. **Keep going hands-free.** The phone advances by itself, and the iPad at the table mirrors the glasses live,
   including what the AI saw and why it decided what it did.

**Six scripts, each taught the way it works:**

| Language | Script | Type | Hero | Taught as |
|---|---|---|---|---|
| Mandarin | Simplified characters | logographic | 你好 | standard stroke order, pinyin with tones |
| Hindi | Devanagari | abugida | नमस्ते | syllable blocks; the headline (top line) drawn last |
| Arabic | Arabic script | abjad, right to left | مرحبا | isolated letters first, then the joined word; dots after the main stroke |
| Russian | Cyrillic | alphabet | Привет | printed letters (cursive looks different, and we say so) |
| Hebrew | Hebrew | abjad, right to left | שלום | block print letters, final forms (ם) |
| Greek | Greek | alphabet | Γεια σου | look-alike letters, the stress accent, final ς |

Each of the 30 items has the native text, romanization, meaning, a one-line "how this script works", a one-line
"why it's useful" (read a menu, write a card), a dictation hint, per-character romanization and native-voice audio.
**Write your name** spells names by sound in Devanagari, Arabic, Cyrillic, Hebrew and Greek.

## How it works

- **Phone (SwiftUI):** picks lessons, starts sessions, shows progress and scores, and falls back to the phone
  camera (Demo Mode). Handoff runs through one shared session on the laptop, so whatever the phone picks the
  glasses show, and vice versa.
- **Glasses + `/live` + `/app` (web):** stroke animation on a black (see-through) display, plus a live view for the
  table with the stroke being drawn, the grade, latency per tier and the tutor agent's steps.
- **Backend (FastAPI, on the laptop):**
  - **3-tier perception pipeline:** tier 1 ink diff (did new ink appear?), tier 2 OpenCV stroke matching against
    the stroke templates (~10–20 ms), tier 3 a local vision model (Qwen2.5-VL 7B on Ollama) for the full grade.
  - **Local tutor agent on Ollama:** observe → evaluate (grade + template comparison in parallel) → decide
    (Qwen2.5 14B, with a 7B fallback past 3 s and rule-based guardrails) → act (pick the next item from your own
    mistake history, react, celebrate milestones).
  - **On-device speech:** pronunciation audio is recorded ahead of time with native-language voices, and
    feedback is spoken on the device.
- **Content:** stroke data for every character of all 30 items. Mandarin uses hanzi-writer-data. Hindi, Arabic,
  Russian, Hebrew and Greek use hand-authored strokes, clearly labelled **"suggested stroke order"**, checked
  over the real font glyph for every character (`content/review/`).

## Privacy

**Handwriting never leaves the laptop.** Photos, grading and the tutor model all run locally on Ollama, with no
cloud API and no account. Graded photos are kept only in a gitignored folder on the laptop (`backend/captures/`),
for debugging, and can be deleted at any time.

## Tech stack

SwiftUI (iOS 17) · FastAPI + Uvicorn (Python 3.12) · OpenCV · Ollama with Qwen2.5-VL 7B, Qwen2.5 14B and
Qwen2.5 7B · plain HTML/JS/SVG (stroke renderer, confetti, Web Audio) · macOS voices for pronunciation audio ·
Python-synthesized sound effects · MicroLumin M6 glasses.

## Culture and accuracy rules we followed

Language and script names only, never flags. No religious, political or slang content, and no stereotypes.
Anything we weren't sure of, we cut. `content/REVIEW.md` lists every item for native speakers to check.

## Credits

- **hanzi-writer** (MIT) and **hanzi-writer-data** (derived from Make Me a Hanzi / Arphic fonts, Arphic Public
  License): Mandarin stroke order.
- **Noto fonts** (SIL Open Font License): Devanagari, Arabic, Hebrew, Greek and CJK text.
- **Ollama** and **Qwen2.5 / Qwen2.5-VL** models.
- **OpenCV**, **FastAPI**.
- Pronunciation audio: macOS system voices (Tingting, Lekha, Majed, Milena, Carmit, Melina).
- Sound effects: synthesized for this project (`content/tools/make_sfx.py`), CC0.
- Hindi, Arabic, Russian, Hebrew and Greek stroke orders: hand-authored for Worn (suggested, not authoritative).
