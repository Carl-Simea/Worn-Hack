# Worn backend (agent A)

FastAPI on the laptop. Local models only (Ollama). One shared live state that the phone, the glasses
view, `/live` and `/app` all read.

```bash
ollama serve                                  # models: qwen2.5vl:7b, qwen2.5:14b, qwen2.5:7b
cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000
ipconfig getifaddr en0                        # the IP the phone uses
uv run pytest                                 # 87 fast tests (models mocked)
uv run pytest -m live                         # + real qwen2.5vl on teammates' handwriting
uv run python eval_handwriting.py --live      # writes test_data/eval_results.md
```

All three models are warmed at startup with small fixed contexts (2k tutor, 4k vision), so they all fit
on a 32 GB Mac at once. Every minute any model Ollama has unloaded (e.g. after an Ollama restart) is
loaded again, so a grade never pays a cold start.

**`/compose` never teaches an unchecked phrase.** The order is:
1. The deterministic word list refuses religious, political, violent or slang messages.
2. If the message is a lesson phrase ("thank you", "water"), the checked lesson content answers it.
3. If `content/phrases/examples.json` (hand-checked, optional) has it, that answers it.
4. Otherwise qwen2.5:14b (patient hedge with 7b) writes it, and an **independent 14b check** back-translates
   it and judges the meaning. A mismatch gets one retry that is told what the text actually said; a second
   mismatch returns an honest "not confident, try something simpler". Only checked answers are cached
   (`data/llm_cache.json`). Mandarin pinyin is computed with pypinyin.

About 45 s after startup, likely demo phrases are prepared in all six languages this way. `/name` answers
from `content/names/examples.json` first, otherwise asks 14b by sound (cached).

## Contract

Errors are JSON `{"detail", "message"}`. `message` is a friendly sentence you can show or speak as-is.

| Route | What |
|---|---|
| `GET /health` | `{ok, langs[], items{lang:n}, models{vision,tutor,tutor_fallback,loaded[],warm,last}, model_ready, glasses}` |
| `GET /content` | `{langs:[lesson]}`. Each lesson has `items` (and the same list as `phrases`); each item has `id, text, chars[], romanization, meaning, audio_url, char_info[{char, stroke_count, stroke_url}]` plus C's extra fields |
| `POST /session` | `{lang, item_id, char_index=0, mode: write\|dictation\|compose, text?}`. `phrase_id` is still accepted. `compose` + `text` translates your message first and makes it the item |
| `GET /session` | the current item: `lang, lang_name, script, rtl, item_id, item{}, text, char, char_index, total_chars, romanization, meaning, audio_url, stroke_url, stroke_count, stroke_index, stroke_order (true\|suggested\|trace), mode, show_char, prompt, version` (404 before the first session) |
| `POST /session/next` | applies the agent's last `next` choice (hands-free advance). 409 if there's nothing to apply |
| `POST /grade` | multipart `image`, `char?`, `lang?` (both default to the session). Returns `{correct, score, feedback, reaction, mood, emoji, sound, seen, template_score, next{lang,item_id,char_index,char,action,reason}, tries, agent{run_id,decided_by,fallback,thought,action}, image_url, latency_ms, tier3_ms, ts, char, lang, item_id, char_index}`. 503 + friendly message if vision is down |
| `GET /session/result` | the last `/grade` result for this session (404 until there is one) |
| `POST /stroke-match` | multipart `image, char, stroke_index (0-based), lang?, diff=false`. Returns `{score, done, stroke_index, stroke_count, next_stroke_index, char_done, ink, hint, template, ordered, latency_ms}`. `diff=true` means the image is only the new ink |
| `POST /ink-diff` | multipart `before, after`. Returns `{new_stroke, new_ink_frac, bbox, aligned, ms}`: the tier-1 reference / fallback |
| `POST /compose` | `{text, lang}`. Returns `{native, romanization, back_translation, chars[], note, model, fallback}`. 422 + friendly message if the text is too long, unsuitable or untranslatable |
| `GET /name?text=` | `{devanagari, arabic, cyrillic, hebrew, greek, note, model}` (approximate, by sound) |
| `POST /event` | `{type, data}`. The iOS dotted names (`glasses.status`, `glasses.show`, `ink`, `voice`, `mode.demo`, `grade.start`, ...) and the generic ones (`glasses`, `phase`, `stroke`, `tier1`, `listening_start/stop`) update the state; every event is logged |
| `GET /live/state` | `{version, session, glasses{connected,showing,phase,stroke,stroke_count,status}, latest_photo_url, last_result, next, agent_steps[], events[], latency{tier1,tier2,tier3,decide,grade:{last_ms,avg_ms,p95_ms,n}} (tier3 = vision read, decide = tutor LLM, grade = whole /grade), progress, listening, last_heard, demo_mode, tries}`. `?since=<version>` returns `{unchanged:true}` when nothing moved |
| `GET /journal?lang=` | `{entries[] newest first, chars[] per-char stats, total, correct}` |
| `GET /review` | Daily 5: `{title, items[{lang,item_id,char_index,char,meaning,romanization,reason,weakness}], count, message}`. Weakest characters first, then new ones; never empty |
| `GET /agent/tools` | the agent's tool catalog + models |
| `POST /reset?journal=true` | clears live state (and memory/journal) before a demo |
| `POST /voice` | multipart `audio` (16 kHz mono WAV, or m4a/aac/mp3 via ffmpeg), `screen`, optional `text` (skips speech-to-text). Returns `{heard, intent, args, say, say_url, nav, hint, session, matcher, ms, stt_ms}`. See **Voice** below |
| `GET /say?text=` | that line as speech: 16 kHz mono 16-bit WAV (macOS `say`, cached in `data/say/`). The glasses have no TTS |
| `POST /app-state` | the glasses report where they are: `{screen, breadcrumb?, hint?, phase?, listening?, last_heard?, lang?, item_id?, char_index?, ...}` (extra fields are kept) |
| `GET /app-state` | `{screen, breadcrumb[], hint, phase, listening, last_heard, last_voice{heard,intent,args,say,nav,ms,ts}, lang, item_id, char_index, daily_index, session, last_result, glasses, + the session's char/text/meaning/romanization/stroke_count/stroke_url/audio_url}` |
| `GET /capture/latest` | the newest photo (`X-Capture-Ts` header). Every photo is also at its `image_url` (`/captures/...`) |
| pages | `/live` and `/mirror` serve `web/live.html`; `/app` serves `web/app.html`; `/app/journal` serves `web/journal.html`; `/print/{lang}` serves `web/print.html`; `/glasses` serves `web/glasses.html` (a friendly placeholder if a file is missing) |
| static | `/static/web/...`, `/static/content/...`, `/captures/...` |

`agent_steps[]`: `{id, run_id, ts, phase: observe|evaluate|decide|act, tool, summary, ms, model, status, data}`.

## Tutor agent (`worn/agent.py`)

Each photo runs **observe → evaluate → decide → act**, and every step is logged to `/live/state`
with its latency:

- **observe**: the target, the item and the learner's memory for this character
- **evaluate**: `grade_character` (qwen2.5vl reads the ink) and `compare_to_template` (OpenCV), run in parallel
- **decide**: qwen2.5:14b picks `advance|retry|review` plus a mood and a spoken reaction (strict JSON).
  It's a hedged call: if 14b hasn't answered by 1 s, qwen2.5:7b starts too; at 3 s whichever answered
  is used, and the whole step stops at 4.5 s. Guardrails: there's no advancing past a miss before 3 tries, and no retry after a
  correct answer. If both models fail, a rule policy decides, and that is logged too.
- **act**: `choose_next_item` (adaptive, from the per-user mistake memory in `data/memory.json`) and `react`

Feedback is never harsh and never about personal style (`agent.kind`). The other tool is
`compose_message` (`/compose`, and `mode: compose`). Cultural content: the `note` fields are built in
code from script facts only; the model never states cultural facts.

## Perception tiers

| tier | where | what | measured |
|---|---|---|---|
| 1 | iPhone (D); reference in `worn/inkdiff.py`, served at `/ink-diff` | ECC-align the photos, lighting-normalized ink, dilated diff | 18/18 on the real pages, 0 false strokes, ~40 ms |
| 2 | `/stroke-match` (`worn/strokes.py`) | ink skeleton vs. the stroke template, chamfer distance, rotation + slant search, relative "stroke k explains the ink better than k-1" test | 96% of strokes accepted across print / cursive-ish / marker / mixed, ~13 ms |
| 3 | `/grade` (`worn/vision.py`) | qwen2.5vl:7b reads the character; the code compares | see `test_data/eval_results.md` |

Ink extraction (shared by tiers 1 and 2) handles real notebook photos: it compares each pixel to the
local paper brightness (so shadows don't matter), uses hysteresis thresholds measured on teammate
photos (ink 0.37–0.69 of the paper, ruled lines ≥ 0.74), strips ruled-line spurs, and drops the
spiral binding, hole punches and specks.

Stroke templates: Mandarin uses hanzi-writer medians (true order). The SVGs in `content/strokes`
are labeled "suggested" when C hand-authored them. Anything else falls back to a font-skeleton
"trace the shape" template, so every character works.

## Languages

Mandarin, Hindi, Arabic, Russian, Hebrew, Greek (Japanese and ASL cut). Content is read live from
`content/*.json` (owned by C), with no restart needed. `backend/seed/` is a Mandarin fallback.

## Env

`WORN_TUTOR_BUDGET` (3), `WORN_HEDGE_AFTER` (1.0), `WORN_DECIDE_CAP` (4.5: the grade's decide step, then rules), `WORN_TUTOR_CTX` (2048), `WORN_VISION_CTX` (4096),
`WORN_KEEP_ALIVE` (12h), `WORN_WARM` (1), `WORN_FAKE_GRADE=1` (a canned pass if vision is down; demo
safety net only), `WORN_DATA_DIR`, `WORN_CAPTURE_DIR`, `WORN_CONTENT_DIR`, `WORN_WEB_DIR`.

## Voice (`worn/voice.py`)

The glasses are voice-first. `/voice` turns speech into a command and a spoken reply that always says what to say next:

1. **Speech-to-text** on this Mac: faster-whisper `base` (int8, CPU, English, biased with the command words), ~250 ms per
   command. Silence and whisper's "hallucinated" prompt become `heard: ""` → "I didn't hear anything. Say ...".
2. **Matching:** C's shared matcher (`content/tools/voice_match.py`, which D also runs on the glasses as an offline
   fallback) goes first, then the backend matcher (fuzzy, mishearings, ordinals like "number two", "how would you say X in Y").
3. **Acting:** the backend does what the screen needs: it starts the lesson session (so `/grade` works without char/lang),
   runs `/compose` and `/name`, and picks the next character / word / Daily 5 item.

Screens: `home, learn, words, lesson (phase watch|your_turn|check|result), name, compose, daily5, journal, howto`
(`daily` and `help` are accepted as aliases). `nav` is `{screen, lang?, item_id?, char_index?, phase?, daily_index?}`
or `null` (stay). `breadcrumb` is rebuilt canonically so "back" is predictable; a lesson remembers if it came from
Daily 5 or Help me write.

| intent | args | backend does |
|---|---|---|
| `home`, `back`, `help` | | nav home / previous screen; `help` speaks this screen's options |
| `open` | `screen` | nav; `daily5` adds `items[]`, `journal` speaks the totals |
| `learn` | `lang`, `items[]` | nav `words` |
| `select` | `lang, item_id` | starts the session, nav `lesson` (a word on the list, "number two", a lesson phrase in "how do I write water in Greek", "practice" after compose) |
| `next`, `previous`, `skip` | | in a lesson's watch/your_turn phase: `args.local`, nav null (the glasses move the stroke); after a result: the agent's next choice, else next char, then next word; on Daily 5 the next item |
| `repeat`, `slower`, `faster`, `show_again`, `retry` | `audio_url`, `speed` | speaks the lesson line again / replays the animation |
| `check` | `lang, char` | nav phase `check`: the glasses take the photo and POST `/grade` |
| `meaning` | | speaks meaning + romanization |
| `compose` | `text, lang, result{/compose}, item_id` | translates (checked), nav `compose`; "practice" writes it |
| `write_name` | `name, result{/name}` | nav `name` |
| `unknown` | | "I didn't catch that. Say ..." |

Every call updates `/app-state.last_voice` and logs a `voice` event `{heard, intent, say, ms, stt_ms}` to `/live/state`.
`WORN_STT_MODEL` (default `base`) picks the whisper size.
