# content/ (owner: agent C)

Lesson JSON, audio, and stroke data. The backend re-reads these on every request, so no restart is needed after edits.

## Files
- `{mandarin,hindi,arabic,russian,japanese}.json`: built by `python3 content/tools/make_content.py`. Edit the tables in that script, not the JSON.
  - Phrase ids are the same in every language: `hello`, `thank_you`, `yes`, `no`, `bathroom`.
  - `chars` holds what the learner writes, one character per `/grade`. Hindi uses aksharas (`स्ते` counts as one). Arabic uses isolated letters in reading order.
  - `audio` is a path relative to `content/`. The backend serves them at `/static/content/...` and returns `null` if the file is missing.
- `audio/{lang}/{id}.m4a`: 25 clips (AAC 64k) made with macOS voices (Tingting, Lekha, Majed, Milena, Kyoko) at a slow rate. Rebuild with `content/tools/make_audio.sh`.
- `strokes/{lang}/{codepoint hex}.{json|svg}`: this follows agent A's `stroke_url()` convention.
  - mandarin `*.json`: hanzi-writer-data 2.0.1 (from Make Me a Hanzi, Arphic license). True stroke order.
  - japanese `*.svg`: KanjiVG stroke centerlines (CC BY-SA 3.0, Ulrich Apel). True stroke order, numbered. **Attribution must appear in the demo credits.**
  - russian, arabic, hindi `*.svg`: hand-made by the team in the same KanjiVG format, built by `python3 content/tools/make_strokes.py` (edit the table there, not the SVGs). `worn-strokes.js` animates them like Japanese. Traced over Noto fonts and ordered by standard handwriting rules (Russian: printed letters; Arabic: isolated forms, body right to left, dots and hamza last; Hindi: body, then stem, then headline last). **Needs a native writer's check.**
  - Hindi conjuncts and syllables with top marks (स्ते न्य हाँ हीं शौ है) are left out on purpose, so they still fall back to "trace the shape" and never show a guessed stroke order.

## web/glasses.html (served at GET /glasses)
- 640×480 on a black background (black is transparent on the optics). Polls `GET /session` and `GET /session/result` every 600 ms.
- A result is shown only if its `ts` is newer than the one already present when the lesson appeared. The check or fix stays on screen 3.5 s and is spoken aloud.
- Dev: open `/glasses` in any browser. Space replays the lesson. `?api=http://IP:8000` points the page at another server.

### Contract for agent B (glasses-android)
- In the WebView, call `setMediaPlaybackRequiresUserGesture(false)`. Otherwise the pronunciation audio and won't autoplay.
- Optional native TTS: `addJavascriptInterface(obj, "WornNative")` with `@JavascriptInterface void speak(String text)`. Without it the page falls back to Web Speech, which may be silent in an Android 9 WebView, so this is recommended.
- `evaluateJavascript` hooks:
  - `worn.capturing()` on button press shows "Checking…".
  - `worn.graded(<json from /grade>)` shows the result right away (optional; polling also catches it).
  - `worn.error("msg")` shows an error.
  - `worn.replay()` replays the animation and audio.

### For agent D (ios)
- Write mode: on `correct`, POST `/session` with `char_index + 1` until `total_chars`, then move to the next phrase.

## web/phone.html: backup phone controller (if the iOS app isn't ready)
Open `http://<laptop-ip>:8000/static/web/phone.html` in iPhone Safari (Share → Add to Home Screen gives it full screen).
It does the iOS app's job: pick a language and phrase, which POSTs /session. It polls /session/result, shows the score, and
auto-advances 1.8 s after a correct answer (next char, then next phrase). It also has Prev and Replay on glasses.

## web/mirror.html: live audience view (iPad or phone)
A landscape iPad view that copies the glasses: the same stroke animation (`web/worn-strokes.js`, shared with glasses.html),
the char, romanization and meaning, the latest handwriting photo, and the grade (✓ or the fix). It polls /session and
/session/result every 500 ms. The LIVE dot turns red (OFFLINE) once the backend hasn't answered for 2 s.
Served at `GET /mirror`. The photo is `result.image_url` if present, else A's `GET /capture/latest` (cache-busted by the grade's `ts`).

ASL was cut on 2026-11-20. The backend still lists `"asl"` in LANG_ORDER and the mode literal, which is harmless.

## web/map.html: phrase map + QA board
All 5 languages × 5 phrases in one grid, coverage per language, every character animated with `worn-strokes.js` (same as the glasses),
audio, QA checkboxes and notes (saved in the browser), and Export QA (Markdown).
- Through the backend: `http://<laptop-ip>:8000/static/web/map.html`. "Glasses" / "Start on glasses" POST `/session`, so it doubles as a test controller.
- Without the backend: `python3 -m http.server 8080` from the repo root, then open `http://localhost:8080/web/map.html`.

## web/stroke-test.html: pre-demo stroke check
Open `http://<laptop-ip>:8000/static/web/stroke-test.html` on any device, ideally the glasses' WebView. It animates every
Mandarin character with `worn-strokes.js` (the code glasses.html and mirror.html use), confirms each one steps through
all its strokes, and checks that /glasses and /mirror respond. It never touches /session, so it's safe to run while live.
