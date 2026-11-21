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

## iOS (D)

9. ~~**The phone no longer follows a session started elsewhere.**~~ **Fixed (D):** the app polls `GET /session` every second,
   remembers the versions it started itself, and opens any newer session from another device (web picker, /live, a teammate)
   at the same item and character, with a "Picked up … from another device" banner. It never interrupts a practice already
   running. Verified in the Simulator against the real backend (screenshots/ios/14-handoff.png). Original report: `API.currentSession()` (GET /session) is defined
   but never called in the rewritten app, so a lesson started from another device (e.g. `POST /session` from the web
   phone picker) doesn't open on the iPhone. Checked in the iOS 27.2 Simulator (iPhone 18 Pro Max) built from
   origin/main `f96a62e`: two external sessions, and the phone stayed on Home. The demo is phone-driven, so this
   doesn't block it. If it's intentional, update `ios/README.md` (it still says "Handoff: it also polls GET /session").
   Otherwise the iOS check passed: the app connects, loads `/content`, `reactions.json`, `milestones.json`, all 9
   `sfx/*.wav` and all 5 `names/*.json`, and the home screen shows all six hero greetings.

10. ~~**(D → A) `GET /name` returns 503 for some names.**~~ **Fixed (A):** names in `examples.json` (David) never touch a model; other names get a 12 s budget (they were hitting the grade's 4.5 s cap) and 14b answers are cached. Original report: Against a private backend from `3e2d767` + working tree (02:40),
    `/name?text=Nyla` and `/name?text=David` returned 503 "I couldn't spell that name right now" (2 of 5 names), and
    every call took 5–8 s. The phone no longer depends on it (it spells instantly on-device from `content/names/*.json`,
    44/58 of C's examples exact, and swaps in the server's spelling when it answers), but the web /app would show the
    error. Repro: `curl -s "localhost:8000/name?text=Nyla"`.
11. ~~**(D → A) Compose and the first grade are slow while models are busy.**~~ **Addressed (A):** lesson phrases are answered from content instantly; likely demo phrases are precomputed with 14b at startup and cached; models are re-warmed every minute. Busy-GPU latency remains: close Xcode/Simulator at the table. Original report: `POST /session {mode:"compose"}` took >20 s
    and the first `/grade` ~10 s on this Mac while other requests were queued on Ollama. The phone shows progress the
    whole time and never times out under 60 s, so it's not blocking; warming both models before the demo helps.

## Found by B (web) against the real backend

9. ~~**`POST /compose {"text":"thank you","lang":"hebrew"}` returns 422**~~ **Fixed (A):** a message that is a lesson phrase now comes straight from the checked content (תודה, no model); the 7b fallback's wrong-script answers are retried with the reason. Original report: "I couldn't turn that into a short message to write."
   Repro: `curl -s -X POST localhost:8000/compose -H 'content-type: application/json' -d '{"text":"thank you","lang":"hebrew"}'`.
   "good morning" in Hebrew and "Happy birthday, my friend" in Mandarin work. תודה is already a lesson item, so a lookup
   in content before the LLM (like /name does with examples.json) would make the obvious phrases never fail. The web page
   shows the message and offers one-tap example messages, so the demo isn't blocked.

10. ~~**`GET /name?text=Maya` returns 503**~~ **Fixed (A):** it was the grade's 4.5 s cap applied to /name; now 12 s, cached, verified on :8000 (Maya answers in all five scripts). Original report: ("I couldn't spell that name right now") three times in a row on a fresh
   backend while the models were loaded; names in `content/names/examples.json` (Anna, David, ...) always work.
   Repro: `curl -s 'localhost:8000/name?text=Maya'`. The web page retries once on 503 and offers the hand-checked
   names as one-tap examples, so the demo can avoid it.

## Machine / setup (whoever is at the laptop)

8. ~~**The Xcode license isn't accepted on this Mac,**~~ **Fixed:** the license was accepted on 11/21, and normal git and the Simulator work. so `/usr/bin/git` fails ("You have not agreed to the Xcode
   license agreements") and Xcode / the iOS Simulator won't run. Workaround used all night:
   `/Library/Developer/CommandLineTools/usr/bin/git`. Real fix (needs your password): `sudo xcodebuild -license accept`.
