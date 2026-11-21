# Bugs and asks outside /content (logged by agent C)

Each entry names its owner. Fix it in your area, then strike it through here.

## Backend (A)

1. ~~**`GET /name` has no offline fallback.**~~ **Fixed (A):** `/name` looks up `content/names/examples.json` first
   (instant, `checked: true`, `model: "checked list"`) and only calls the LLM for other names.
2. ~~**New stroke files need a backend restart.**~~ **Fixed (A):** templates are cached per file mtime, so edits
   under `content/strokes` apply live.
3. ~~**Sessions don't carry the teaching lines.**~~ **Fixed (A):** `session.item` carries `how`, `why` and
   `dictation`; in dictation mode `session.prompt` is `item.dictation`.

## Web (B)

5. ~~**`/app` overflows horizontally at iPhone width (390 px).**~~ **Not a page bug (B):** Chrome's `--headless --window-size=390,…`
   lays the page out at its ~500 px minimum window width and then crops the image to 390, so everything looks cut off.
   With a real 390 px viewport (Playwright, `web/dev/shoot.py`, which also asserts no sideways scroll) /app, /live,
   /app/journal and /print fit at 390, 1180 and 1440 px. Screenshots in `screenshots/web/`. Original report: (Re-checked with a longer time budget: still there.) In headless Chrome at 390×844 the header ("Jou…"),
   the intro text and the right-hand cards ("Help me write", "Journal") are cut off at the right edge, and the page
   scrolls sideways. Probably a fixed min-width or a 2-column grid without `minmax(0,1fr)`.
6. ~~`/live` and `/glasses` idle overlay over an active lesson~~ **Not a bug:** a headless-Chrome capture artifact
   (a CSS fade frozen mid-way). With a longer time budget both pages are clean. Retracted by C.
7. ~~**Greek `γεια σου` shows as one word in the character strip**~~ **Fixed (B):** `WornInk.segments(item.text, chars)`
   puts the word gap back on /live, /glasses and /app. Original report: (`γ ε ι α σ ο υ`). `chars` leaves out the space on
   purpose (no empty writing step), so use `item.text` to place the gap: there's a word break wherever `text` has a space.

## Machine / setup (whoever is at the laptop)

8. **The Xcode license isn't accepted on this Mac,** so `/usr/bin/git` fails ("You have not agreed to the Xcode
   license agreements") and Xcode / the iOS Simulator won't run. Workaround used all night:
   `/Library/Developer/CommandLineTools/usr/bin/git`. Real fix (needs your password): `sudo xcodebuild -license accept`.
