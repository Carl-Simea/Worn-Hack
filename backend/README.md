# Worn backend (agent A)

    cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000

Needs `ollama serve` running with `qwen2.5vl:7b` pulled. The model is warmed on startup.
Laptop IP for the phone and glasses: `ipconfig getifaddr en0`.

Env: `WORN_VISION_MODEL`, `WORN_OLLAMA_URL`, `WORN_GRADE_TIMEOUT` (45s),
`WORN_FAKE_GRADE=1` (demo safety net: if the model is down, return a canned pass instead of a 503).

## Notes for teammates
- **Content (C):** `content/{lang}.json` is re-read on every request, so there's no restart.
  `backend/seed/mandarin.json` is used only until `content/mandarin.json` exists.
  Asset paths in lesson JSON (`audio`, `asl`) are relative to `content/` and served at `/static/content/<path>`;
  a path that doesn't exist on disk comes back as `null`.
- **Stroke animations (C):** put them at `content/strokes/{lang}/{codepoint-hex}.{svg|gif|webm|mp4|json}`,
  e.g. 你 is `content/strokes/mandarin/4f60.svg`. `stroke_url` is filled in automatically.
- **/glasses (C):** serves `web/glasses.html` if it exists, else `backend/glasses_fallback.html`.
- **Polling:** `GET /session` includes `version`, which bumps on every new session. `/session/result` returns 404 until a grade
  for the current session exists, and `ts` changes on each grade.
- **/grade (B):** `char` and `lang` are optional; they default to the active session. Response:
  `{correct, score, feedback, seen, char, lang, ts, latency_ms}`. A 503 means the grader is down.
- Every graded photo is saved to `backend/captures/` (gitignored) for debugging.
