# Bugs and asks outside /content (logged by agent C)

Each entry names its owner. Fix it in your area, then strike it through here.

## Backend (A)

1. **`GET /name` has no offline fallback.** It's pure LLM, so if the tutor model is down or slow the demo's
   "write your name" beat returns an error. Found with the model off: `GET /name?text=Maria` →
   `"I couldn't spell that name right now."`
   **Fix (about 5 lines):** `content/names/examples.json` has 10 checked names (Adam, Anna, David, Emma, John,
   Lina, Lisa, Maria, Mike, Sam) in exactly `/name`'s keys (`devanagari, arabic, cyrillic, hebrew, greek`).
   Look the lowercase name up there first (instant, always right) and fall back to the LLM only for other names.
2. **New stroke files need a backend restart.** `strokes.template()` is `lru_cache`d, so a stroke file added
   while the server runs still reports `stroke_order: "trace"` until restart. Fine for the demo, but don't
   edit strokes during it.
3. **Sessions don't carry the teaching lines.** `build_session()` copies only `id, text, chars, romanization,
   meaning` into `session.item`. The lessons also have `how` (how the script works), `why` (why it's useful),
   `dictation` (a hint for dictation mode), `char_romanization` and a per-language `hero`. Adding
   `how/why/dictation` to `session.item` would let the glasses and /live show them without reading /content.
   In dictation mode, `item.dictation` is a better `prompt` than the generic "Listen, then write what you hear."

## Machine / setup (whoever is at the laptop)

4. **The Xcode license isn't accepted on this Mac,** so `/usr/bin/git` fails ("You have not agreed to the Xcode
   license agreements") and Xcode / the iOS Simulator won't run. Workaround used all night:
   `/Library/Developer/CommandLineTools/usr/bin/git`. Real fix (needs your password): `sudo xcodebuild -license accept`.
