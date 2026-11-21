# content/ (owner: agent C)

Lesson JSON, audio, and stroke data. The backend re-reads these on every request, so no restart is needed after edits.

## Files
- `{mandarin,hindi,arabic,russian,japanese,asl}.json`: built by `python3 content/tools/make_content.py`. Edit the tables in that script, not the JSON.
  - Phrase ids are the same in every language: `hello`, `thank_you`, `yes`, `no`, `bathroom`.
  - `chars` holds what the learner writes, one character per `/grade`. Hindi uses aksharas (`स्ते` counts as one). Arabic uses isolated letters in reading order. ASL has `chars: []` and `text` is the gloss.
  - `audio` and `asl` are paths relative to `content/`. The backend serves them at `/static/content/...` and returns `null` if the file is missing.
- `audio/{lang}/{id}.m4a`: 25 clips (AAC 64k) made with macOS voices (Tingting, Lekha, Majed, Milena, Kyoko) at a slow rate. Rebuild with `content/tools/make_audio.sh`.
- `strokes/{lang}/{codepoint hex}.{json|svg}`: this follows agent A's `stroke_url()` convention.
  - mandarin `*.json`: hanzi-writer-data 2.0.1 (from Make Me a Hanzi, Arphic license). True stroke order.
  - japanese `*.svg`: KanjiVG stroke centerlines (CC BY-SA 3.0, Ulrich Apel). True stroke order, numbered. **Attribution must appear in the demo credits.**
  - russian, arabic, hindi `*.svg`: hand-made by the team in the same KanjiVG format, built by `python3 content/tools/make_strokes.py` (edit the table there, not the SVGs). Traced over Noto fonts and ordered by standard handwriting rules (Russian: printed letters; Arabic: isolated forms, body right to left, dots and hamza last; Hindi: body, then stem, then headline last). **Needs a native writer's check.**
  - Hindi conjuncts and syllables with top marks (स्ते न्य हाँ हीं शौ है) are left out on purpose, so they still fall back to "trace the shape" and never show a guessed stroke order.

## web/map.html: phrase map + QA board
Every language × phrase × character in one page, with live stroke-order animation, audio, coverage per language, QA checkboxes and notes (saved in the browser), and Export QA (Markdown).
- Through the backend: `http://<laptop-ip>:8000/static/web/map.html`. "Glasses" / "Start on glasses" POST `/session`, so it doubles as a test controller.
- Without the backend: `python3 -m http.server 8080` from the repo root, then open `http://localhost:8080/web/map.html`.
- `asl/{id}.mp4`: **TODO(team): not recorded yet.** Five short clips (hello, thank_you, yes, no, bathroom) filmed on a phone against a plain background, landscape, 2–3 s, H.264 mp4, ideally signed by someone who knows ASL. Drop them in here and they go live; until then the glasses show "ASL video not recorded yet".

## web/glasses.html (served at GET /glasses)
- 640×480 on a black background (black is transparent on the optics). Polls `GET /session` and `GET /session/result` every 600 ms.
- A result is shown only if its `ts` is newer than the one already present when the lesson appeared. The check or fix stays on screen 3.5 s and is spoken aloud.
- Dev: open `/glasses` in any browser. Space replays the lesson. `?api=http://IP:8000` points the page at another server.

### Contract for agent B (glasses-android)
- In the WebView, call `setMediaPlaybackRequiresUserGesture(false)`. Otherwise the pronunciation audio and ASL video won't autoplay.
- Optional native TTS: `addJavascriptInterface(obj, "WornNative")` with `@JavascriptInterface void speak(String text)`. Without it the page falls back to Web Speech, which may be silent in an Android 9 WebView, so this is recommended.
- `evaluateJavascript` hooks:
  - `worn.capturing()` on button press shows "Checking…".
  - `worn.graded(<json from /grade>)` shows the result right away (optional; polling also catches it).
  - `worn.error("msg")` shows an error.
  - `worn.replay()` replays the animation and audio.

### For agent D (ios)
- Write mode: on `correct`, POST `/session` with `char_index + 1` until `total_chars`, then move to the next phrase.
- ASL: use `lang:"asl"` with `mode:"asl"`. Any other language with `mode:"asl"` also works, because every phrase carries `asl`.

## web/phone.html: backup phone controller (if the iOS app isn't ready)
Open `http://<laptop-ip>:8000/static/web/phone.html` in iPhone Safari (Share → Add to Home Screen gives it full screen).
It does the iOS app's job: pick a language and phrase, which POSTs /session. It polls /session/result, shows the score, and
auto-advances 1.8 s after a correct answer (next char, then next phrase). It also has Prev, Replay on glasses, and an ASL toggle.
