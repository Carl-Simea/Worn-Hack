# Worn: demo script (60 seconds)

Track 02 · Seamless Handoff. Demo Sat 2:15pm at our table. Submissions close 2:00pm.

**Roles:** one person writes and narrates ("the learner"). A second person drives the laptop and watches `/live` on the iPad.

## The 60 seconds

| Time | Show | Say |
|---|---|---|
| 0:00 | iPhone home screen: 你好 · नमस्ते · مرحبا · Привет · שלום · Γεια σου | "Six scripts most Americans can't read. Worn teaches you to **write** them on real paper, hands-free, through your glasses." |
| 0:08 | Tap **Mandarin → 你好**. The glasses (and the iPad on `/live`) animate 你 stroke by stroke, and it says *nǐ hǎo*. | "I pick a word on my phone. It hands off to the glasses: stroke order, sound, meaning." |
| 0:18 | Write 你 on paper with the marker, then tap the glasses (or press **Grade** in Demo Mode). | "I write it for real, with a pen." |
| 0:24 | Check + ding + a goofy line ("Chef's kiss!"). The phone jumps to 好 on its own, and `/live` shows the three perception tiers with their latency. | "A local vision model and a tutor agent grade my handwriting in a couple of seconds. On a miss I'd get one specific fix, like 'add the dot on top'." |
| 0:34 | Write 好. Ta-da plus sparkle: **"Your first word in Mandarin!"** | "Two characters and I've written my first word." |
| 0:42 | Phone: **Write your name**, type *Maria* (a checked name: instant, works offline), get **Μαρία / मारिया / Мария**. Write the Greek or Russian one. | "And everyone's favourite: your own name in a new script." |
| 0:55 | Point at the laptop. | "No cloud: the photos of your handwriting never leave this laptop. Worn: wear it, write it." |

If there's time, the strongest extra beat is **Arabic مرحبا**: isolated letters first, then the joined word, all right to left. It shows the "how this script works" line on screen.

## Table setup checklist (do it at 1:30pm)

- [ ] **Quit Xcode and the iOS Simulator on the laptop** (they share the GPU: grading goes from ~2–3 s to 6–8 s).
- [ ] Laptop on power, on the `event` wifi. Note its IP: `ipconfig getifaddr en0`.
- [ ] `ollama serve` running. `ollama list` shows `qwen2.5vl:7b`, `qwen2.5:14b` and `qwen2.5:7b`.
- [ ] Backend: `cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000`. Then `curl localhost:8000/health` should show 6 languages and the models loaded.
- [ ] **Content check, before the demo and never during it** (it changes the session): `python3 content/tools/check_content.py http://127.0.0.1:8000` should print `0 problems`. Then reset: `curl -X POST localhost:8000/reset`.
- [ ] iPad: Safari at `http://<laptop-ip>:8000/live`, full screen, landscape, brightness up.
- [ ] iPhone: Worn app opened and connected to `<laptop-ip>`. Local Network allowed.
- [ ] Glasses charged and connected (see `ios/README.md`). If not: turn on **Demo Mode (phone camera)** in the app.
- [ ] Paper: plain white, with a **thick black marker** (thin grey pencil is hard to see). Good light, no glare.
- [ ] Volume up on the phone and glasses (dings and pronunciation).
- [ ] Warm-up run: write 你 once and see a check. The first grade warms the models.

## Backup plan

| If this breaks | Do this |
|---|---|
| Glasses won't connect or the camera fails | In the iOS app, turn on **Demo Mode (phone camera)**: same lesson, the phone grades with its own camera. Keep `/live` on the iPad as the "glasses view". |
| Grading feels slow (>5 s) | Quit Xcode, the Simulator and anything else using the GPU. The tutor falls back to rules after 4.5 s, so it always answers. |
| Vision model is slow or down | Restart the backend with `WORN_FAKE_GRADE=1` (a canned pass instead of an error). Say "the model is warming up" and keep going. |
| iPhone app misbehaves | Open `http://<laptop-ip>:8000/static/web/phone.html` on any phone: a web phone picker with the same handoff. |
| Venue wifi drops | Put the laptop, phone and iPad on the laptop's hotspot (or a phone hotspot), then use the new laptop IP. |
| "Write your name" is slow or errors | Use a **checked name**: Maria, John, Emma, Anna, Sam, Mike, Lisa, Lina, Adam, David. They answer instantly from `content/names/examples.json`, even with the model off. |
| Something looks wrong in a script | Switch to Mandarin 你好 (the most tested path). |
| Everything is down | Show `content/review/strokes_*.png` (every character, stroke by stroke, all 6 scripts) and talk through the flow. |

## Things to never do mid-demo
- Don't run `check_content.py` (it changes the session).
- Don't restart Ollama (models take ~30 s to load).
- Don't pick Arabic/Hebrew first if the learner isn't comfortable writing right to left. Mandarin is the safe opener.
- **Don't demo Hebrew שלום** (or any item with ש): the vision model misreads ש as ע or ב about half the time. For Hebrew, use מים (water) or חבר (friend).
- Grading takes ~2–3 s with the GPU quiet (the tutor's decide step is capped at 4.5 s). Fill the pause: "it's reading my handwriting right now, all on this laptop."
