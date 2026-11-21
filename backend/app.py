"""Worn backend (agent A): the contract every client builds against. See backend/README.md.

Run:  cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from worn import agent, compose, config, content, inkdiff, llm, memory, strokes, vision
from worn.live import LIVE

log = logging.getLogger("worn")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = []
    if config.WARM_MODELS:
        tasks.append(asyncio.create_task(llm.keep_warm()))
        tasks.append(asyncio.create_task(_prefetch_later()))
    yield
    for t in tasks:
        t.cancel()


async def _prefetch_later():
    """After warm-up, precompute likely demo phrases with 14b (cached in data/llm_cache.json)."""
    await asyncio.sleep(45)
    try:
        await compose.prefetch()
    except Exception as e:
        log.warning("prefetch stopped: %s", e)


app = FastAPI(title="Worn", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Capture-Ts"])

if config.CONTENT_DIR.is_dir():
    app.mount("/static/content", StaticFiles(directory=config.CONTENT_DIR), name="content")
if config.WEB_DIR.is_dir():
    app.mount("/static/web", StaticFiles(directory=config.WEB_DIR), name="web")
app.mount("/captures", StaticFiles(directory=config.CAPTURE_DIR), name="captures")


@app.exception_handler(HTTPException)
async def friendly_errors(_req, exc: HTTPException):
    """Every error has a human sentence in `message` that clients can show or speak as-is."""
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse({"detail": detail, "message": detail}, status_code=exc.status_code)


# ------------------------------------------------------------------ health + content

@app.get("/health")
async def health():
    loaded = await llm.loaded_models()
    langs = content.ordered()
    return {
        "ok": True,
        "version": LIVE.version,
        "langs": [l["lang"] for l in langs],
        "items": {l["lang"]: len(l["items"]) for l in langs},
        "models": {
            "vision": config.VISION_MODEL, "tutor": config.TUTOR_MODEL, "tutor_fallback": config.TUTOR_FALLBACK,
            "loaded": loaded, "warm": llm.status["warm"], "last": llm.status["last"],
        },
        # kept for older clients (iOS settings, phone.html)
        "model": config.VISION_MODEL,
        "model_ready": config.VISION_MODEL in loaded,
        "fake_grade": config.FAKE_GRADE,
        "glasses": LIVE.glasses,
    }


@app.get("/content")
def get_content():
    return {"langs": content.ordered()}


# ------------------------------------------------------------------ session

class SessionIn(BaseModel):
    lang: str
    item_id: str | None = None
    phrase_id: str | None = None  # old name, still accepted
    char_index: int = 0
    mode: Literal["write", "dictation", "compose"] = "write"
    text: str | None = Field(None, description="compose mode: the learner's own message (English)")


_composed: dict[str, dict] = {}  # compose-mode items: id -> {lang, item}
_compose_ids = itertools.count(1)


def _lookup(lang: str, item_id: str) -> tuple[dict, dict]:
    if item_id in _composed and _composed[item_id]["lang"] == lang:
        lesson = content.load().get(lang) or {"lang": lang, **config.LANGS.get(lang, {})}
        return lesson, _composed[item_id]["item"]
    found = content.find_item(lang, item_id)
    if not found:
        langs = content.load()
        if lang not in langs:
            raise HTTPException(404, f"I don't have lessons for {lang!r} yet. Try one of: {', '.join(sorted(langs))}.")
        raise HTTPException(404, f"There's no item {item_id!r} in {lang}.")
    return found


def build_session(lang: str, item: dict, lesson: dict, char_index: int, mode: str) -> dict:
    chars = item.get("chars") or []
    if not chars:
        raise HTTPException(400, "That item has nothing to write.")
    if not 0 <= char_index < len(chars):
        raise HTTPException(400, f"char_index must be between 0 and {len(chars) - 1}.")
    char = chars[char_index]
    n_strokes = strokes.stroke_count(lang, char)
    tm = strokes.template(lang, char)
    dictation = mode == "dictation"
    return {
        "lang": lang,
        "lang_name": lesson.get("name") or config.LANGS.get(lang, {}).get("name", lang),
        "script": lesson.get("script") or config.LANGS.get(lang, {}).get("script"),
        "rtl": bool(lesson.get("rtl", config.LANGS.get(lang, {}).get("rtl", False))),
        "item_id": item["id"],
        "phrase_id": item["id"],
        "item": {k: item.get(k) for k in ("id", "text", "chars", "romanization", "meaning", "how", "why", "dictation")
                 if item.get(k) is not None},
        "text": item.get("text"),
        "char": char,
        "char_index": char_index,
        "total_chars": len(chars),
        "romanization": item.get("romanization"),
        "char_romanization": (item.get("char_romanization") or [None] * len(chars))[char_index]
        if isinstance(item.get("char_romanization"), list) and len(item["char_romanization"]) == len(chars) else None,
        "meaning": item.get("meaning"),
        "audio_url": item.get("audio_url") or content.static_url(item.get("audio")),
        "stroke_url": strokes.stroke_url(lang, char),
        "stroke_count": n_strokes,
        "stroke_index": 0,
        "stroke_order": "trace" if tm.get("trace") else ("true" if tm.get("ordered") else "suggested"),
        "mode": mode,
        "show_char": not dictation,
        "prompt": (item.get("dictation") or "Listen, then write what you hear.") if dictation else
                  ("Write your message, one character at a time." if mode == "compose" else "Watch, then write it on paper."),
        "back_translation": item.get("back_translation"),
        "note": item.get("note"),
    }


@app.post("/session")
async def post_session(s: SessionIn):
    if s.mode == "compose" and s.text:
        try:
            out = await agent.run_compose(s.text, s.lang)
        except compose.ComposeError as e:
            raise HTTPException(422, str(e))
        iid = f"compose-{next(_compose_ids)}"
        item = {"id": iid, "text": out["native"], "chars": out["chars"], "romanization": out["romanization"],
                "meaning": out["text"], "back_translation": out["back_translation"], "note": out["note"]}
        _composed[iid] = {"lang": s.lang, "item": item}
        lesson, it = _lookup(s.lang, iid)
    else:
        iid = s.item_id or s.phrase_id
        if not iid:
            raise HTTPException(400, "Send item_id (or text with mode 'compose').")
        lesson, it = _lookup(s.lang, iid)
    sess = build_session(s.lang, it, lesson, s.char_index, s.mode)
    LIVE.set_session(sess)
    log.info("session %s/%s char %s (%s)", s.lang, it["id"], s.char_index, s.mode)
    return sess


@app.get("/session")
def get_session():
    if LIVE.session is None:
        raise HTTPException(404, "No lesson yet. Pick one on the phone.")
    return LIVE.session


@app.post("/session/next")
def session_next():
    """Apply the agent's last decision (result.next): the hands-free way to move on."""
    nxt = LIVE.next
    if not nxt or not nxt.get("item_id") or LIVE.session is None:
        raise HTTPException(409, "Nothing to move to yet. Write a character first.")
    lesson, it = _lookup(nxt["lang"], nxt["item_id"])
    sess = build_session(nxt["lang"], it, lesson, nxt["char_index"], LIVE.session.get("mode", "write"))
    LIVE.set_session(sess)
    return sess


@app.get("/session/result")
def get_result():
    if LIVE.result is None:
        raise HTTPException(404, "No result yet for this character.")
    return LIVE.result


# ------------------------------------------------------------------ perception tiers

async def _read_image(image: UploadFile) -> bytes:
    raw = await image.read()
    if not raw:
        raise HTTPException(400, "The photo was empty. Try again.")
    return raw


def _save_capture(jpeg: bytes, lang: str, char: str) -> str:
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}_{lang}_{ord(char[0]):x}.jpg"
    (config.CAPTURE_DIR / name).write_bytes(jpeg)
    return f"/captures/{name}"


@app.post("/grade")
async def grade(image: UploadFile = File(...), char: str | None = Form(None), lang: str | None = Form(None)):
    """Tier 3 + the tutor agent. char/lang default to the active session."""
    sess = LIVE.session
    char = (char or (sess or {}).get("char") or "").strip()
    lang = (lang or (sess or {}).get("lang") or "").strip()
    if not char or not lang:
        raise HTTPException(400, "I need to know which character this is. Start a lesson first.")
    raw = await _read_image(image)
    try:
        jpeg = vision.prep_image(raw)
    except Exception:
        raise HTTPException(400, "That file isn't a photo I can read.")
    url = _save_capture(jpeg, lang, char)
    LIVE.set_photo(url)
    LIVE.glasses.update({"phase": "checking", "showing": "checking"})
    try:
        res = await agent.run_grade(jpeg, char, lang, sess, url)
    except Exception as e:
        log.error("grade failed: %r", e)
        LIVE.add_event("grade_error", {"error": str(e)[:200]})
        raise HTTPException(503, "The checker is warming up. Try again in a moment.")
    LIVE.set_result(res, res.get("next"))
    return res


@app.post("/stroke-match")
async def stroke_match(image: UploadFile = File(...), char: str | None = Form(None),
                       stroke_index: int = Form(0), lang: str | None = Form(None), diff: bool = Form(False)):
    """Tier 2: OpenCV, < 300 ms. lang defaults to the session (or is guessed from the char)."""
    sess = LIVE.session or {}
    char = (char or sess.get("char") or "").strip()
    lang = (lang or (sess.get("lang") if sess.get("char") == char else None) or _guess_lang(char))
    if not char or not lang:
        raise HTTPException(400, "I need the character to compare against.")
    raw = await _read_image(image)
    t0 = time.perf_counter()
    try:
        res = await asyncio.to_thread(strokes.match_stroke, raw, lang, char, stroke_index, diff)
    except Exception as e:
        log.warning("stroke-match failed: %r", e)
        raise HTTPException(400, "I couldn't read that photo.")
    ms = (time.perf_counter() - t0) * 1000
    res.update({"char": char, "lang": lang, "latency_ms": int(ms)})
    LIVE.latency("tier2", ms)
    if sess.get("char") == char:
        LIVE.set_stroke(res["next_stroke_index"] if res["done"] and not res["char_done"] else res["stroke_index"],
                        res["stroke_count"])
    LIVE.add_step("t2", "evaluate", f"Stroke {res['stroke_index'] + 1}/{res['stroke_count']}: "
                  f"{res['score']}/100 {'done' if res['done'] else 'not yet'}", tool="compare_to_template", ms=ms,
                  data={k: res[k] for k in ("score", "done", "stroke_index", "stroke_count")})
    return res


@app.post("/ink-diff")
async def ink_diff(before: UploadFile = File(...), after: UploadFile = File(...)):
    """Tier 1 reference/fallback (the iPhone normally does this on-device)."""
    b, a = await _read_image(before), await _read_image(after)
    try:
        res = await asyncio.to_thread(inkdiff.diff, b, a)
    except Exception:
        raise HTTPException(400, "I couldn't compare those photos.")
    LIVE.latency("tier1", res["ms"])
    return res


def _guess_lang(char: str) -> str | None:
    from worn import scripts
    for lang in config.LANG_ORDER:
        if char and scripts.in_script(char, lang):
            return lang
    return None


# ------------------------------------------------------------------ compose + name

class ComposeIn(BaseModel):
    text: str
    lang: str


@app.post("/compose")
async def post_compose(c: ComposeIn):
    try:
        return await agent.run_compose(c.text, c.lang)
    except compose.ComposeError as e:
        raise HTTPException(422, str(e))


@app.get("/name")
async def get_name(text: str = Query(..., max_length=60)):
    try:
        out, meta = await compose.name(text)
    except compose.ComposeError as e:
        raise HTTPException(422, str(e))
    except llm.LLMError:
        raise HTTPException(503, "I couldn't spell that name right now. Try again in a moment.")
    return {**out, "model": meta.get("model")}


# ------------------------------------------------------------------ events + live

class EventIn(BaseModel):
    type: str = Field(..., max_length=40)
    data: dict[str, Any] | None = None


@app.post("/event")
def post_event(e: EventIn):
    return {"ok": True, "event": LIVE.apply_event(e.type, e.data), "version": LIVE.version}


@app.get("/live/state")
def live_state(since: int | None = None):
    """Everything /live needs. Pass ?since=<version> to get {"unchanged": true} when nothing moved."""
    if since is not None and since == LIVE.version:
        return {"unchanged": True, "version": LIVE.version}
    s = LIVE.session or {}
    prog = memory.progress(s.get("lang"), s.get("item_id"), s.get("char_index", 0)) if s else {}
    return LIVE.snapshot(progress=prog)


@app.get("/agent/tools")
def agent_tools():
    return {"tools": agent.tool_catalog(), "models": {"tutor": config.TUTOR_MODEL,
            "fallback": config.TUTOR_FALLBACK, "vision": config.VISION_MODEL, "budget_s": config.TUTOR_BUDGET}}


# ------------------------------------------------------------------ journal + review

@app.get("/journal")
def get_journal(lang: str | None = None, limit: int = Query(100, ge=1, le=500)):
    entries = memory.journal(lang, limit=limit)
    by_char: dict[str, dict] = {}
    for e in entries:
        k = f"{e['lang']}:{e['char']}"
        st = by_char.setdefault(k, {"lang": e["lang"], "char": e["char"], "attempts": 0, "correct": 0,
                                    "best": 0, "last_ts": e["ts"]})
        st["attempts"] += 1
        st["correct"] += 1 if e.get("correct") else 0
        st["best"] = max(st["best"], e.get("score") or 0)
    return {"lang": lang, "entries": entries, "chars": sorted(by_char.values(), key=lambda c: -c["last_ts"]),
            "total": len(entries), "correct": sum(1 for e in entries if e.get("correct"))}


@app.get("/review")
def get_review():
    items = memory.daily5()
    return {"title": "Daily 5", "items": items, "count": len(items),
            "message": "Five quick characters to keep them fresh." if items else "Write a few characters first."}


@app.post("/reset")
def reset_demo(journal: bool = False):
    """Clear the live state (and the journal/memory with ?journal=true) before a demo."""
    LIVE.reset()
    if journal:
        memory.reset()
    return {"ok": True}


# ------------------------------------------------------------------ photos

@app.get("/capture/latest")
def capture_latest():
    shots = sorted(config.CAPTURE_DIR.glob("*.jpg"), key=lambda f: f.stat().st_mtime)
    if not shots:
        raise HTTPException(404, "No photos yet.")
    f = shots[-1]
    return FileResponse(f, media_type="image/jpeg", headers={
        "X-Capture-Ts": f"{f.stat().st_mtime:.3f}", "Cache-Control": "no-store"})


# ------------------------------------------------------------------ pages (owned by /web)

def _page(*candidates: str) -> FileResponse:
    for c in candidates:
        p = Path(c) if c.startswith("/") else config.WEB_DIR / c
        if p.exists():
            return FileResponse(p, media_type="text/html", headers={"Cache-Control": "no-cache"})
    fallback = config.HERE / "pages" / "missing.html"
    return FileResponse(fallback, media_type="text/html", status_code=200)


@app.get("/live", response_class=HTMLResponse)
@app.get("/mirror", response_class=HTMLResponse)
def page_live():
    return _page("live.html", "mirror.html")


@app.get("/app", response_class=HTMLResponse)
def page_app():
    return _page("app.html", "phone.html")


@app.get("/app/journal", response_class=HTMLResponse)
def page_journal():
    return _page("journal.html")


@app.get("/print/{lang}", response_class=HTMLResponse)
def page_print(lang: str):
    return _page("print.html")


@app.get("/glasses", response_class=HTMLResponse)
def page_glasses():
    return _page("glasses.html", str(config.HERE / "glasses_fallback.html"))
