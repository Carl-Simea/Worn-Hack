# Worn Learn: Duolingo-style phone app (owner: Favor)

`web/learn.html` + `web/learn/curriculum.js`. Pick a lesson on the phone; every writing step pops up on the glasses.

## Open it
- iPhone on the event wifi: `http://<laptop-ip>:8000/static/web/learn.html`, then Share → Add to Home Screen for full screen.
- No backend: `python3 -m http.server 8080` from the repo root → `http://localhost:8080/web/learn.html`. Writing steps then use “I wrote it” instead of the glasses.
- `?unlock=1` (or Profile → Unlock every lesson) opens the whole path for a demo.

## The path (every language)
1 character at a time → 2 at a time → 3 at a time → short words → full phrases → review of all five.
Mandarin is hand-built so words make sense: 不 · 是 · 你 · 好 → 你好 · 谢谢 · 厕所 → 在哪里 → 厕所在哪里？ → review.
The other four are generated from `content/{lang}.json` in the same shape (short phrases first: yes, no, hello, thank you, bathroom).

## Inside a lesson
- **New character**: stroke animation, sound, meaning, 🔊 (phone speech).
- **Write on paper**: the phone POSTs `/session` (write mode). Glasses show “Ready… Go!”, then the strokes loop slow → faster → full speed. Press the glasses button; the phone polls `/session/result` and shows the score. 📷 Phone camera posts to `/grade` as a backup.
- **Quick check / Listen / Translate**: multiple choice. A wrong answer costs a ❤️; a wrong drawing never does.
- XP, day streak, hearts and finished lessons are saved on the phone (localStorage).

## Glasses changes that ship with this
- `web/worn-strokes.js`: opt-in `{ ramp: true }` plays each loop slow → faster → full speed and labels it.
- `web/glasses.html`: “Ready… Go!” before every new character, then animation + pronunciation; uses the ramp.
- `web/mirror.html`: uses the ramp so the audience view matches the glasses.

No backend or lesson-JSON changes: every step is an existing `phrase_id` + `char_index`.
Edit what each character sounds like, or the Mandarin order, in `web/learn/curriculum.js`.
