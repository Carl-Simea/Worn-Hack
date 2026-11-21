# Worn: demo script (60 seconds)

Track 02 · Seamless Handoff. Demo Sat 2:15pm at our table. Submissions close 2:00pm.

**Roles:** one person wears the glasses, writes and **talks** ("the learner"). A second person drives the laptop and watches `/live` on the iPad (it mirrors the real glasses display).

The wearer controls everything by speaking. Every glasses screen shows what to say next, and "what can I say" reads the options aloud. The button is a backup only (press = next or open the highlighted item, hold = check, double tap = back). Every phrase and hint: `content/voice/commands.json` and `screens.json`.

## The 60 seconds (voice-first)

| Time | Wearer says | Glasses show / say | Narrate |
|---|---|---|---|
| 0:00 | (Home) | 你好 · नमस्ते · مرحبا · Привет · שלום · Γεια σου, *Say "learn", "daily five" or "help"* | "Six scripts most Americans can't read. Worn teaches you to **write** them on real paper, hands-free." |
| 0:06 | **"Learn Mandarin."** | Word list, *Say a word, like "hello"* | "No phone, no taps. I just talk to my glasses." |
| 0:10 | **"Hello."** | 你 animates stroke by stroke, says *nǐ hǎo* | "Stroke order, sound and meaning." |
| 0:16 | (writes 你 with the marker) **"I'm done."** | *Checking your writing…*, then a check, a ding and a goofy line | "A local vision model and a tutor agent grade my pen on paper in a couple of seconds." |
| 0:28 | **"Next."** then writes 好, **"I'm done."** | Ta-da, rainbow confetti: **"Your first word in Mandarin!"** | "My first word." |
| 0:40 | **"Write my name, Maria."** then **"Greek."** | **Μαρία** (also मारिया / Мария) | "Everyone's favourite: your own name in a new script." |
| 0:50 | **"How do I write good morning in Greek?"** | **Καλημέρα** with its romanization | "Or anything you want to say." |
| 0:56 | Point at the laptop. | | "No cloud: the photos never leave this laptop. Worn: wear it, write it." |

If a command isn't heard, say it again in fewer words ("next", "check", "home"). If the room is too loud, use the button (press = next, hold = check, double tap = back) and keep narrating.

If there's time, the strongest extra beat is **"Learn Arabic." → "Hello."**: isolated letters first, then the joined word, all right to left.

## Table setup checklist (do it at 1:30pm)

- [ ] **Quit Xcode and the iOS Simulator on the laptop** (they share the GPU: grading goes from ~2–3 s to 6–8 s).
- [ ] Laptop on power, on the `event` wifi. Note its IP: `ipconfig getifaddr en0`.
- [ ] `ollama serve` running. `ollama list` shows `qwen2.5vl:7b`, `qwen2.5:14b` and `qwen2.5:7b`.
- [ ] Backend: `cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000`. Then `curl localhost:8000/health` should show 6 languages and the models loaded.
- [ ] **Content check, before the demo and never during it** (it changes the session): `python3 content/tools/check_content.py http://127.0.0.1:8000` should print `0 problems`. Then reset: `curl -X POST localhost:8000/reset`.
- [ ] iPad: Safari at `http://<laptop-ip>:8000/live`, full screen, landscape, brightness up.
- [ ] (Backup only) iPhone: Worn app opened and connected to `<laptop-ip>`, Local Network allowed.
- [ ] Glasses charged, Worn app open on them, connected to `http://<laptop-ip>:8000` (USB `adb reverse` is the fallback, see `glasses-android/README.md`). Say "what can I say" once: it should answer.
- [ ] **Mic check in the real room:** say "home", "learn Greek", "back", "I'm done". If something is misheard, tell agent C (aliases are in `content/tools/make_voice.py`).
- [ ] Paper: plain white, with a **thick black marker** (thin grey pencil is hard to see). Good light, no glare.
- [ ] Optional: print a worksheet from `http://<laptop-ip>:8000/print/mandarin` (A4/Letter at 100%). The 3 cm boxes are sized for the glasses camera, and the stroke steps are printed next to each character.
- [ ] Volume up on the phone and glasses (dings and pronunciation).
- [ ] Warm-up run: write 你 once and see a check. The first grade warms the models.

## Backup plan

| If this breaks | Do this |
|---|---|
| Voice isn't heard (noisy room) | Use the button: press = next / open, hold = check, double tap = back. Speak close and short: "next", "check", "home". |
| Glasses won't connect or the camera fails | In the iOS app, turn on **Demo Mode (phone camera)**: same lesson, the phone grades with its own camera. Keep `/live` on the iPad as the "glasses view". |
| Nothing can drive the glasses, but you need `/live` to move | From the laptop: `uv run --with pillow python web/dev/sim_glasses.py http://127.0.0.1:8000 --lang mandarin --item hello`. It posts what the iPhone + glasses would (strokes, photos, grade, confetti) and `/live` shows it all. Say it's a replay. |
| Grading feels slow (>5 s) | Quit Xcode, the Simulator and anything else using the GPU. The tutor falls back to rules after 4.5 s, so it always answers. |
| Vision model is slow or down | Restart the backend with `WORN_FAKE_GRADE=1` (a canned pass instead of an error). Say "the model is warming up" and keep going. |
| iPhone app misbehaves | Open `http://<laptop-ip>:8000/app` in Safari on any phone: the whole learner flow on the web, same lesson and handoff (the glasses follow it). **Check with phone camera** grades a photo if the glasses camera fails. |
| Venue wifi drops | Put the laptop, phone and iPad on the laptop's hotspot (or a phone hotspot), then use the new laptop IP. |
| "Write your name" is slow or errors | Use a **checked name**: Maria, John, Emma, Anna, Sam, Mike, Lisa, Lina, Adam, David. They answer instantly from `content/names/examples.json`, even with the model off. |
| Something looks wrong in a script | Switch to Mandarin 你好 (the most tested path). |
| Everything is down | Show `content/review/strokes_*.png` (every character, stroke by stroke, all 6 scripts) and talk through the flow. |

## Things to never do mid-demo
- Don't run `check_content.py` (it changes the session).
- Don't restart Ollama (models take ~30 s to load).
- Don't pick Arabic/Hebrew first if the learner isn't comfortable writing right to left. Mandarin is the safe opener.
- **Lead with Hebrew מים (water) or חבר (friend), not שלום.** The vision model alone misread ש as ע or ב about half the time. A now settles look-alikes with the stroke templates (14/14 right and 14/14 wrong letters on real paper), but ש is still the riskiest Hebrew letter on stage.
- Grading takes ~2–3 s with the GPU quiet (the tutor's decide step is capped at 4.5 s). Fill the pause: "it's reading my handwriting right now, all on this laptop."
