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

5. **`/app` overflows horizontally at iPhone width (390 px).** In headless Chrome at 390×844 the header ("Jou…"),
   the intro text and the right-hand cards ("Help me write", "Journal") are cut off at the right edge, and the page
   scrolls sideways. Probably a fixed min-width or a 2-column grid without `minmax(0,1fr)`.
6. **`/live`: the idle overlay sits on top of an active lesson.** With a session active (e.g. Arabic مرحبا), the big
   "Worn · Waiting for the first lesson" watermark and the hero row (你好 नमस्ते مرحبا Привет שלום Γεια σου) are drawn
   across the On-paper panel, the Agent-brain panel and the gap between them. They should hide once `/live/state`
   has a session.
   The same thing shows on `/glasses` (640×480): the "Worn · Pick a phrase on your phone" idle screen stays
   half-visible over the lesson. Caveat: I captured both with headless Chrome (`--virtual-time-budget`), which can
   freeze a CSS fade mid-way, so please confirm in a real browser.
7. **Greek `γεια σου` shows as one word in the character strip** (`γ ε ι α σ ο υ`). `chars` leaves out the space on
   purpose (no empty writing step), so use `item.text` to place the gap: there's a word break wherever `text` has a space.

## Machine / setup (whoever is at the laptop)

8. **The Xcode license isn't accepted on this Mac,** so `/usr/bin/git` fails ("You have not agreed to the Xcode
   license agreements") and Xcode / the iOS Simulator won't run. Workaround used all night:
   `/Library/Developer/CommandLineTools/usr/bin/git`. Real fix (needs your password): `sudo xcodebuild -license accept`.
