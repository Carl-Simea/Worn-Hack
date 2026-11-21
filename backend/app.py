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
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from worn import agent, compose, config, content, inkdiff, llm, memory, screen, strokes, vision
from worn.live import LIVE
from worn.autograde import AUTO
from worn.camera import RELAY, BOUNDARY as CAM_BOUNDARY, mjpeg as cam_mjpeg, decode_b64

log = logging.getLogger("worn")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = [asyncio.create_task(asyncio.to_thread(V.warm_stt))] if config.WARM_MODELS else []
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


async def _grade_bytes(raw: bytes, char: str | None, lang: str | None, source: str = "still") -> dict:
    """The full grade (shape + Scribi's rubric). Used by POST /grade (stills) and the auto-grader (previews)."""
    sess = LIVE.session
    char = (char or (sess or {}).get("char") or "").strip()
    lang = (lang or (sess or {}).get("lang") or "").strip()
    if not char or not lang:
        raise HTTPException(400, "I need to know which character this is. Start a lesson first.")
    AUTO.analyzing(0)
    try:
        jpeg = vision.prep_image(raw)
    except Exception:
        raise HTTPException(400, "That file isn't a photo I can read.")
    url = _save_capture(jpeg, lang, char)
    LIVE.set_photo(url)
    LIVE.glasses.update({"phase": "checking", "showing": "checking"})
    try:
        res = await agent.run_grade(jpeg, char, lang, sess, url, progress=AUTO.analyzing)
    except Exception as e:
        log.error("grade failed: %r", e)
        LIVE.add_event("grade_error", {"error": str(e)[:200]})
        AUTO.publish("result", error="checker unavailable")
        raise HTTPException(503, "The checker is warming up. Try again in a moment.")
    res["source"] = source
    if AUTO.key and LIVE.session and AUTO.key[:2] == (lang, char):
        res["stroke_scores"] = list(AUTO.scores)  # live tier-2 accuracy per stroke while writing
    LIVE.set_result(res, res.get("next"))
    AUTO.result(res)
    return res


@app.post("/grade")
async def grade(image: UploadFile = File(...), char: str | None = Form(None), lang: str | None = Form(None)):
    """Full grade of a full-res still. char/lang default to the active session. Also answers the
    auto-grader's capture request (grading.capture_request in /app-state)."""
    raw = await _read_image(image)
    AUTO.still_arrived()
    return await _grade_bytes(raw, char, lang, "still")


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
    V.reset_state()
    AUTO.reset()
    AUTO.grade_fn = _auto_grade
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


@app.get("/glasses/screen.mjpg")
def glasses_screen_mjpg():
    """Live mirror of the glasses display (adb screencap over USB, ~5 fps). Never errors: unplugged = placeholder frames."""
    return StreamingResponse(screen.mjpeg(), media_type=f"multipart/x-mixed-replace; boundary={screen.BOUNDARY}",
                             headers={"Cache-Control": "no-store"})


@app.get("/glasses/screen.jpg")
async def glasses_screen_jpg():
    st = await screen.grab()
    if not st["ok"]:
        raise HTTPException(503, f"Glasses screen unavailable: {st['error']}")
    return Response(st["jpeg"], media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/glasses/screen/status")
async def glasses_screen_status():
    """{connected, error, capture_ms, size, ...}: whether /glasses/screen.mjpg is showing the real display."""
    if screen.status()["age_s"] is None or screen.status()["age_s"] > 2:
        await screen.grab()
    return screen.status()


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


# ------------------------------------------------------------------ voice (glasses are voice-first)

from worn import voice as V  # noqa: E402
from worn import voice_agent as VA  # noqa: E402


def _lang_name(lang: str | None) -> str:
    return config.LANGS.get(lang or "", {}).get("name", lang or "")


def _start_item(lang: str, item_id: str, char_index: int = 0, mode: str = "write") -> dict:
    lesson, it = _lookup(lang, item_id)
    sess = build_session(lang, it, lesson, char_index, mode)
    LIVE.set_session(sess)
    return sess


def _lesson_say(sess: dict, lead: str = "") -> str:
    rom = sess.get("char_romanization") or sess.get("romanization") or ""
    part = (f" Letter {sess['char_index'] + 1} of {sess['total_chars']}." if sess.get("total_chars", 1) > 1 else "")
    return (f"{lead}{sess.get('meaning') or ''}, in {sess.get('lang_name')}: {rom}.{part} "
            f"Watch the strokes, then write it. Say check when you're done.").strip()


def _lesson_nav(sess: dict) -> dict:
    return {"screen": "lesson", "lang": sess["lang"], "item_id": sess["item_id"], "char_index": sess["char_index"],
            "phase": "watch"}


def _step(delta: int, *, from_agent: bool) -> dict | None:
    """Next/previous character, then next/previous word in that language (wraps)."""
    s = LIVE.session
    if not s:
        return None
    if from_agent and LIVE.next and LIVE.result and LIVE.next.get("item_id"):
        n = LIVE.next
        return _start_item(n["lang"], n["item_id"], n["char_index"], s.get("mode", "write"))
    ci = s["char_index"] + delta
    if 0 <= ci < s["total_chars"]:
        return _start_item(s["lang"], s["item_id"], ci, s.get("mode", "write"))
    items = (content.load().get(s["lang"]) or {}).get("items") or []
    ids = [i["id"] for i in items]
    if s["item_id"] not in ids or not ids:
        return None
    j = (ids.index(s["item_id"]) + delta) % len(ids)
    ci = 0 if delta > 0 else len(items[j]["chars"]) - 1
    return _start_item(s["lang"], ids[j], ci)


def _voice_ctx(screen: str | None) -> tuple[dict, str, dict, dict]:
    st = V.get_state()
    screen = V.norm_screen(screen or st.get("screen"))
    langs = content.load()
    ctx_lang = st.get("lang") or (LIVE.session or {}).get("lang")
    ctx = {"lang": ctx_lang, "items": (langs.get(ctx_lang) or {}).get("items") or [], "langs": langs}
    return st, screen, langs, ctx


async def _act(intent: str, args: dict, screen: str | None, heard: str) -> dict:
    """Execute one intent server-side (session, compose, name, ...) → {intent, args, say, nav, session}."""
    st, screen, langs, ctx = _voice_ctx(screen)
    sess = LIVE.session
    ctx_lang = ctx["lang"]
    args = dict(args or {})
    nav: dict | None = None
    say = ""
    out_sess = None
    in_lesson = screen == "lesson" and sess is not None

    if intent == "home":
        nav, say = {"screen": "home"}, f"Hi, I'm {V.ASSISTANT}. " + V.HINTS["home"]
    elif intent == "back":
        bc = list(st.get("breadcrumb") or ["home"])
        if not bc or any(b not in V.SCREENS for b in bc) or bc[-1] != screen:  # display names from the glasses
            bc = V.breadcrumb(screen, None, [b for b in bc if b in V.SCREENS])
        prev = bc[-2] if len(bc) >= 2 else "home"
        nav = {"screen": prev, **({"lang": ctx_lang} if prev in ("words", "lesson") and ctx_lang else {})}
        say = {"words": f"{_lang_name(ctx_lang)} words. " + V.HINTS["words"], "learn": V.HINTS["learn"]}.get(
            prev, f"Back. {V.HINTS.get(prev, V.HINTS['home'])}")
    elif intent == "open":
        scr = args["screen"]
        nav = {"screen": scr}
        if scr == "daily5":
            d5 = memory.daily5()
            first = d5[0] if d5 else None
            args["items"] = d5
            say = ("Your Daily 5. First: " + f"{first['meaning']} in {_lang_name(first['lang'])}. Say start."
                   if first else V.HINTS["daily5"])
        elif scr == "journal":
            ent = memory.journal(limit=500)
            ok = sum(1 for e in ent if e.get("correct"))
            say = (f"Your journal: {len(ent)} tries, {ok} correct. " if ent else "Your journal is empty so far. ") + \
                V.HINTS["journal"]
        else:
            say = {"learn": "Pick a language. ", "howto": f"Just talk to {V.ASSISTANT}. Here's what you can say. ", "name": "Write my name. ",
                   "compose": "Help me write. "}.get(scr, "") + V.HINTS.get(scr, "")
    elif intent == "learn":
        lang = args["lang"]
        if lang not in langs:
            say = f"I don't have {_lang_name(lang)} lessons yet. " + V.HINTS["learn"]
        else:
            nav = {"screen": "words", "lang": lang}
            words = ", ".join(i.get("meaning") or i["id"] for i in langs[lang]["items"])
            say = f"{_lang_name(lang)}. Say a word: {words}. Or say back."
            args["items"] = [{"id": i["id"], "text": i.get("text"), "meaning": i.get("meaning"),
                              "romanization": i.get("romanization")} for i in langs[lang]["items"]]
    elif intent == "select":
        lang = args.get("lang") or ctx_lang
        out_sess = _start_item(lang, args["item_id"], int(args.get("char_index") or 0), args.get("mode") or "write")
        nav, say = _lesson_nav(out_sess), _lesson_say(out_sess)
    elif intent == "next" and in_lesson and st.get("phase") in ("watch", "your_turn"):
        # inside a lesson "next" moves watch → your turn → next stroke; the glasses do that themselves
        nav, say = None, ""
        args["local"] = True
    elif intent in ("next", "skip", "previous"):
        from_daily = screen == "daily5" or (in_lesson and "daily5" in (st.get("breadcrumb") or []) and intent != "previous")
        if from_daily or (intent == "next" and args.get("start")):
            d5 = memory.daily5()
            k = 0 if (args.get("start") or screen == "daily5") else int(st.get("daily_index") or 0) + 1
            if d5:
                k %= len(d5)
                d = d5[k]
                out_sess = _start_item(d["lang"], d["item_id"], d["char_index"])
                V.update_state({"daily_index": k}, source="backend")
                nav, say = {**_lesson_nav(out_sess), "daily_index": k}, _lesson_say(out_sess, f"Daily {k + 1} of {len(d5)}. ")
        elif sess and screen in ("lesson", "words"):
            out_sess = _step(-1 if intent == "previous" else 1, from_agent=intent == "next")
            if out_sess:
                nav = _lesson_nav(out_sess)
                say = _lesson_say(out_sess, "Skipped. " if intent == "skip" else "")
        if not nav:
            say = "There's nothing to move to here. " + V.HINTS.get(screen, V.HINTS["home"])
    elif intent in ("repeat", "slower", "show_again"):
        if in_lesson:
            if intent == "slower":
                args["speed"] = 0.5
            args["audio_url"] = sess.get("audio_url")
            say = {"repeat": _lesson_say(sess), "slower": "Slower. Watch each stroke.",
                   "show_again": "Watch again."}[intent]
            nav = {**_lesson_nav(sess)} if intent != "repeat" else None
        else:
            lv = st.get("last_voice") or {}
            say = lv.get("say") or V.HINTS.get(screen, V.HINTS["home"])
    elif intent == "check":
        if sess:
            args.update({"lang": sess["lang"], "char": sess["char"]})
            say = "Hold the paper still. Checking."
            nav = {**_lesson_nav(sess), "phase": "check"}
            asyncio.create_task(AUTO.final("voice: check", manual=True))  # still if the glasses send one, else preview
        else:
            say = "Pick a word first. " + V.HINTS["home"]
    elif intent == "meaning":
        if sess:
            say = (f"{sess.get('text')} means {sess.get('meaning')}. It's said {sess.get('romanization')}. "
                   f"You're writing letter {sess['char_index'] + 1} of {sess['total_chars']}.")
            say = say.replace(f"{sess.get('text')} means", "This means") if not sess.get("text", "").isascii() else say
        else:
            say = "Pick a word first, then ask what it means. " + V.HINTS["home"]
    elif intent == "compose":
        lang, text = args.get("lang"), args["text"]
        if not lang:
            say = f'Which language? Say: how do I write {text} in Mandarin, or Hindi, Arabic, Russian, Hebrew, Greek.'
            nav = {"screen": "compose"}
        else:
            lesson_hit = next((i for i in (langs.get(lang) or {}).get("items", [])
                               if V.norm(i.get("meaning") or "") == V.norm(text)), None)
            if lesson_hit:
                intent = "select"
                args = {"lang": lang, "item_id": lesson_hit["id"], "text": text}
                out_sess = _start_item(lang, lesson_hit["id"])
                nav, say = _lesson_nav(out_sess), _lesson_say(out_sess, "That's one of your lessons. ")
            else:
                try:
                    res = await agent.run_compose(text, lang)
                    iid = f"compose-{next(_compose_ids)}"
                    _composed[iid] = {"lang": lang, "item": {
                        "id": iid, "text": res["native"], "chars": res["chars"], "romanization": res["romanization"],
                        "meaning": res["text"] if "text" in res else text,
                        "back_translation": res["back_translation"], "note": res["note"]}}
                    args.update({"result": res, "item_id": iid})
                    nav = {"screen": "compose", "lang": lang, "item_id": iid}
                    if args.get("guided"):  # "write water" / "write this word": straight into the stroke lesson
                        out_sess = _start_item(lang, iid, 0, "compose")
                        nav = _lesson_nav(out_sess)
                    say = (f"In {_lang_name(lang)}, {text} is: {res['romanization']}. "
                           f"{len(res['chars'])} to write. Say practice to write it, or ask for another phrase.")
                except compose.ComposeError as e:
                    nav, say = {"screen": "compose"}, f"{e} " + V.HINTS["compose"]
                except llm.LLMError:
                    nav, say = {"screen": "compose"}, "I can't translate right now. Try a lesson word instead."
    elif intent == "write_name":
        try:
            res, meta = await compose.name(args["name"])
            args["result"] = {**res, "model": meta.get("model")}
            nav = {"screen": "name", "name": args["name"]}
            say = f"Here's {args['name']} in five scripts. Say another name, or home."
        except compose.ComposeError as e:
            nav, say = {"screen": "name"}, f"{e} " + V.HINTS["name"]
        except llm.LLMError:
            nav, say = {"screen": "name"}, "I couldn't spell that name right now. Try again in a moment."
    elif intent == "help":
        nav = None
        say = "You can say: " + V.HINTS.get(screen, V.HINTS["howto"]).removeprefix("Say ")
    else:
        if args.get("reason") == "silence":
            say = "I didn't hear anything. " + V.HINTS.get(screen, V.HINTS["home"])
        else:
            say = "I didn't catch that. " + V.HINTS.get(screen, V.HINTS["home"])

    # "practice" on the compose screen writes the composed message
    if intent == "practice":
        last = ((st.get("last_voice") or {}).get("args") or {})
        iid = last.get("item_id") or st.get("item_id")
        lang = last.get("lang") or st.get("lang")
        if iid in _composed and lang:
            intent, args = "select", {"lang": lang, "item_id": iid, "mode": "compose"}
            out_sess = _start_item(lang, iid, 0, "compose")
            nav, say = _lesson_nav(out_sess), _lesson_say(out_sess)
        else:
            intent, say = "unknown", "Ask for a phrase first. " + V.HINTS["compose"]
    if intent in ("retry", "faster"):
        if in_lesson:
            args["speed"] = 1.5 if intent == "faster" else 1.0
            nav = {**_lesson_nav(sess), "phase": "your_turn" if intent == "retry" else "watch"}
            say = "Okay, again. Write it when you're ready." if intent == "retry" else "Faster."
        else:
            say = V.HINTS.get(screen, V.HINTS["home"])
    if intent == "exit":
        nav, say = {"screen": "idle"}, f"Bye! Say 'Hey {V.ASSISTANT}' anytime."
    elif intent == "wake":
        nav, say = {"screen": "home"}, f"Hi, I'm {V.ASSISTANT}. What would you like to do?"
    return {"intent": intent, "args": args, "say": say, "nav": nav, "session": out_sess}


def _action(r: dict) -> dict | None:
    """One executed step as an absolute action the glasses can apply (never relative, so nothing runs twice)."""
    i, a, nav = r["intent"], r.get("args") or {}, r.get("nav") or {}
    if i == "home":
        return {"tool": "go_home", "args": {}}
    if i == "exit":
        return {"tool": "exit_app", "args": {}}
    if i == "wake":
        return {"tool": "wake", "args": {}}
    if r.get("session") and nav.get("screen") == "lesson":
        s = r["session"]
        return {"tool": "open_word", "args": {"lang": s["lang"], "item_id": s["item_id"], "char_index": s["char_index"]}}
    if i == "next" and a.get("local"):
        return {"tool": "next_stroke", "args": {}}
    if i == "learn" and nav:
        return {"tool": "learn_language", "args": {"lang": nav.get("lang")}}
    if i in ("open", "back") and nav:
        return {"tool": "open_screen", "args": {k: v for k, v in nav.items() if k in ("screen", "lang")}}
    if i in ("compose", "write_name") and a.get("result"):
        return {"tool": i, "args": {k: a[k] for k in ("text", "lang", "name", "result", "item_id") if k in a}}
    if i == "repeat":
        return {"tool": "repeat", "args": {"url": a.get("audio_url")}}
    if i in ("slower", "faster", "show_again", "check", "meaning", "help", "retry", "skip", "previous"):
        return {"tool": i, "args": {k: a[k] for k in ("speed", "lang", "char") if k in a}}
    return None


_LAST_VOICE: dict = {"key": None, "ts": 0.0, "out": None}
DEDUPE_S = 2.5

CONFIRM = {"home": "Going home!", "back": "Going back!", "next": "Next one!", "previous": "Back one!",
           "repeat": "Again!", "slower": "Slowing down!", "faster": "Speeding up!", "show_again": "Watch again!",
           "check": "Checking!", "skip": "Skipping!"}


def _confirm(r: dict) -> str:
    """2-4 words said as the action happens, so the wearer always knows it worked."""
    i, a, nav = r["intent"], r.get("args") or {}, r.get("nav") or {}
    if not nav and i not in ("repeat", "slower", "faster", "show_again", "check"):
        return ""
    if i in CONFIRM:
        return CONFIRM[i]
    if i == "learn":
        return f"Opening {_lang_name(nav.get('lang')).split()[0]}!"
    if i == "select" and r.get("session"):
        return f"Let's write {r['session'].get('meaning') or r['session'].get('text')}!"
    if i == "compose" and a.get("text"):
        return f"Let's write {a['text']}!"
    if i == "write_name" and a.get("name"):
        return f"Writing {a['name']}!"
    if i == "open":
        return {"journal": "Opening your journal!", "daily5": "Opening Daily 5!", "learn": "Pick a language!",
                "compose": "Let's write a word!", "name": "Let's write your name!",
                "howto": "Here's how!"}.get(nav.get("screen"), "")
    return ""


async def _do_voice(heard: str, screen: str | None) -> dict:
    key = (V.norm(heard), V.norm_screen(screen))
    if key[0] and _LAST_VOICE["key"] == key and time.time() - _LAST_VOICE["ts"] < DEDUPE_S and _LAST_VOICE["out"]:
        return {**_LAST_VOICE["out"], "duplicate": True, "actions": [], "session": None}  # same clip posted twice
    out = await _do_voice_once(heard, screen)
    _LAST_VOICE.update({"key": key, "ts": time.time(), "out": out})
    return out


async def _do_voice_once(heard: str, screen: str | None) -> dict:
    run = agent.Run("voice")
    st, scr, langs, ctx = _voice_ctx(screen)
    p = await VA.plan(heard, scr, st, ctx)
    tools = p.get("tools")
    run.step("decide", f'Heard "{heard[:60]}" → ' + (", ".join(f"{t['tool']}{t['args'] or ''}" for t in tools)
             if tools else ", ".join(i["intent"] for i in p["intents"]) or "nothing")
             + (f" (confidence {p['confidence']:.1f})" if p.get("confidence") is not None else ""),
             tool="understand", ms=p["ms"], model=VA.MODEL if p["via"] == "model" else p["via"],
             data={"via": p["via"], "heard": heard, "intents": p["intents"], "error": p.get("error")})
    results, cur = [], scr
    for step in p["intents"]:
        t = time.perf_counter()
        r = await _act(step["intent"], step["args"], cur, heard)
        results.append(r)
        nav = r["nav"] or {}
        if nav.get("screen"):
            cur = V.norm_screen(nav["screen"]) if nav["screen"] != "idle" else "idle"
            V.update_state({"screen": cur, **{k: nav[k] for k in ("lang", "item_id", "char_index", "phase") if k in nav}},
                           source="voice")
        run.step("act", f"{r['intent']}: {(r['say'] or '')[:70]}", tool=r["intent"], ms=(time.perf_counter() - t) * 1000)
    with V._state_lock:
        V.STATE["pending"] = p.get("pending")  # one open question at a time; any answer clears it
    last = results[-1] if results else {"intent": "unknown", "args": {}, "say": "", "nav": None, "session": None}
    said = next((r["say"] for r in reversed(results) if r["say"]), "")
    if p.get("via") == "chat":  # Scribi's own line first, then the facts only a tool can give
        from worn import companion
        facts = next((r["say"] for r in reversed(results) if r["say"] and companion.facts_line(r["intent"])), "")
        said = " ".join(x for x in (p.get("chat_say") or "", facts) if x).strip()
        companion.remember(heard, said, [st["tool"] for st in (p.get("tools") or [])])
    say = " ".join(x for x in (said, p.get("say") or "") if x).strip()
    conf = next((c for c in (_confirm(r) for r in reversed(results)) if c), "")
    if conf and not say.startswith(conf):
        say = f"{conf} {say}".strip()
    nav = next((r["nav"] for r in reversed(results) if r["nav"]), None)
    sess = next((r["session"] for r in reversed(results) if r["session"]), None)
    intent = "ask" if (p.get("pending") and not results) else ("chat" if p.get("via") == "chat" and not results
                                                                  else last["intent"])
    args = last.get("args") or {}
    VA.remember(heard, p["intents"], say)
    return {"intent": intent, "args": args, "say": say, "nav": nav, "session": sess, "matcher": p["via"],
            "actions": [a for a in (_action(r) for r in results) if a], "steps": [
                {"intent": r["intent"], "args": {k: v for k, v in (r["args"] or {}).items() if k != "items"},
                 "nav": r["nav"]} for r in results], "pending": p.get("pending"), "understand_ms": p["ms"]}


@app.post("/voice")
async def post_voice(request: Request, audio: UploadFile | None = File(None), screen: str | None = Form(None),
                     text: str | None = Form(None), request_id: str | None = Form(None), id: str | None = Form(None),
                     req: str | None = Form(None)):
    """Glasses mic → {heard, intent, args, say, say_url, nav, hint, session?, ms}. `text` skips speech-to-text."""
    t0 = time.perf_counter()
    stt_ms = None
    if text is not None and text.strip():
        heard = text.strip()[:300]
    elif audio is not None:
        raw = await audio.read()
        t1 = time.perf_counter()
        try:
            heard = await asyncio.to_thread(V.transcribe, raw, audio.filename or "audio.wav", screen)
        except V.STTError as e:
            log.warning("stt: %s", e)
            heard = ""
        stt_ms = round((time.perf_counter() - t1) * 1000)
    else:
        raise HTTPException(400, "Send audio (or text).")
    try:
        r = await _do_voice(heard, screen)
    except HTTPException as e:
        r = {"intent": "unknown", "args": {}, "say": f"{e.detail} " + V.HINTS.get(screen or "home", ""), "nav": None,
             "session": None}
    ms = round((time.perf_counter() - t0) * 1000)
    new_screen = (r["nav"] or {}).get("screen") or screen or V.get_state().get("screen")
    hint = V.HINTS.get(new_screen, V.HINTS["home"])
    rid = request_id or id or req or request.headers.get("x-request-id")
    out = {"heard": heard, **r, "request_id": rid, "say_url": f"/say?text={quote(r['say'])}" if r["say"] else None, "hint": hint,
           "ms": ms, "stt_ms": stt_ms, "ts": time.time()}
    voice_rec = {k: out[k] for k in ("heard", "intent", "args", "say", "nav", "ms", "ts")}
    voice_rec["args"] = {k: v for k, v in (r["args"] or {}).items() if k not in ("items",)}
    nav = r["nav"] or {}
    V.update_state({"screen": new_screen, "last_heard": heard, "last_voice": voice_rec, "listening": False,
                    "hint": hint, **{k: nav[k] for k in ("lang", "item_id", "char_index", "phase") if k in nav}},
                   source="voice")
    LIVE.last_heard = heard or LIVE.last_heard
    LIVE.listening = False
    LIVE.add_event("voice", {"heard": heard, "intent": r["intent"], "say": r["say"], "ms": ms, "stt_ms": stt_ms})
    log.info("voice [%s] %r → %s %s (%d ms)", screen, heard, r["intent"], nav.get("screen"), ms)
    return out


@app.get("/say")
async def get_say(text: str = Query(..., min_length=1, max_length=400)):
    """Any line as speech: 16 kHz mono 16-bit WAV (macOS say), cached. The glasses have no TTS."""
    try:
        f = await asyncio.to_thread(V.say_file, text)
    except Exception as e:
        raise HTTPException(503, f"I can't speak right now ({e}).")
    return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})


class AppStateIn(BaseModel):
    model_config = {"extra": "allow"}
    screen: str | None = None


def _sync_session(f: dict) -> None:
    """The glasses are the source of truth for which lesson is open: after a backend restart (or a lesson the
    glasses opened on their own) rebuild the session, so /grade and auto-grading know the character."""
    if V.norm_screen(f.get("screen")) != "lesson" or not f.get("lang") or not f.get("item_id"):
        return
    try:
        ci = int(f.get("char_index") or 0)
    except (TypeError, ValueError):
        ci = 0
    s = LIVE.session or {}
    if (s.get("lang"), s.get("item_id"), s.get("char_index")) == (f["lang"], f["item_id"], ci):
        return
    try:
        _start_item(f["lang"], f["item_id"], ci, s.get("mode", "write") if s.get("item_id") == f["item_id"] else "write")
        LIVE.add_event("session_sync", {"lang": f["lang"], "item_id": f["item_id"], "char_index": ci})
    except HTTPException as e:
        log.warning("app-state lesson %s/%s#%s not found: %s", f["lang"], f["item_id"], ci, e.detail)


@app.post("/app-state")
def post_app_state(s: AppStateIn):
    """The glasses report where they are: {screen, breadcrumb, hint, phase, listening, last_heard, lang, ...}."""
    fields = s.model_dump(exclude_none=True)
    _sync_session(fields)
    st = V.update_state(fields, source="glasses")
    if "listening" in fields:
        LIVE.listening = bool(fields["listening"])
    if fields.get("last_heard"):
        LIVE.last_heard = fields["last_heard"]
    LIVE.glasses.update({"connected": True, "last_seen": time.time(), "screen": st.get("screen")})
    LIVE.add_event("app_state", {k: fields[k] for k in ("screen", "phase") if k in fields})
    return {"ok": True, **st}


@app.get("/app-state")
def get_app_state():
    st = V.get_state()
    s = LIVE.session or {}
    st.update({"listening": LIVE.listening or st.get("listening", False),
               "last_heard": st.get("last_heard") or LIVE.last_heard,
               "hint": st.get("hint") or V.HINTS.get(st.get("screen") or "home"),
               "session": LIVE.session, "last_result": LIVE.result,
               **{k: s.get(k) for k in ("lang_name", "char", "total_chars", "romanization", "meaning", "text",
                                        "stroke_count", "stroke_url", "audio_url", "mode") if s},
               "glasses": LIVE.glasses})
    if s and not st.get("lang"):
        st.update({"lang": s.get("lang"), "item_id": s.get("item_id"), "char_index": s.get("char_index")})
    return st


# ------------------------------------------------------------------ camera relay (glasses preview frames)

async def _auto_grade(jpeg: bytes, source: str) -> dict:
    try:
        return await _grade_bytes(jpeg, None, None, source)
    except HTTPException as e:
        AUTO.publish("result", error=e.detail)
        raise


AUTO.grade_fn = _auto_grade
RELAY.listeners.append(AUTO.on_frame)


@app.websocket("/ws/camera")
async def ws_camera(ws: WebSocket, role: str | None = None):
    """Glasses: send binary JPEG frames (optionally a JSON text message {ts, seq, w, h} right before each, or
    {ts, jpeg: base64}). Viewers: receive a JSON text meta message then the binary JPEG, newest frame only.
    ?role=pub never receives frames; ?role=view never publishes. Without a role, sending a frame makes you a publisher."""
    await ws.accept()
    state = {"pub": role == "pub", "meta": None}
    if state["pub"]:
        RELAY.publishers += 1
    else:
        RELAY.viewers += 1

    async def sender():
        seq = RELAY.seq - 1 if RELAY.jpeg else 0
        while True:
            if state["pub"]:
                await asyncio.sleep(1)
                continue
            seq, jpeg, meta = await RELAY.wait_newer(seq, timeout=5)
            if jpeg is None or state["pub"]:
                continue
            await ws.send_json({k: meta.get(k) for k in ("ts", "seq", "w", "h", "recv_ts")})
            await ws.send_bytes(jpeg)

    task = asyncio.create_task(sender()) if role != "pub" else None
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if role == "view":
                continue
            data, text = msg.get("bytes"), msg.get("text")
            meta = None
            if text:
                try:
                    obj = __import__("json").loads(text)
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj.get("jpeg"):
                    data, meta = decode_b64(obj["jpeg"]), obj
                elif isinstance(obj, dict):
                    state["meta"] = obj
                    continue
            if data:
                if not state["pub"]:
                    state["pub"] = True
                    RELAY.viewers -= 1
                    RELAY.publishers += 1
                try:
                    await RELAY.publish(data, meta or state["meta"])
                except ValueError:
                    pass
                state["meta"] = None
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if task:
            task.cancel()
        if state["pub"]:
            RELAY.publishers -= 1
        else:
            RELAY.viewers -= 1


@app.post("/camera/frame")
async def camera_frame(image: UploadFile = File(...), ts: float | None = Form(None)):
    """HTTP fallback for publishing one preview frame."""
    try:
        meta = await RELAY.publish(await image.read(), {"ts": ts} if ts else None)
    except ValueError:
        raise HTTPException(400, "That frame isn't a JPEG.")
    return {"ok": True, "seq": meta["seq"]}


@app.get("/camera.mjpg")
def camera_mjpg():
    """Newest preview frame as multipart MJPEG (latest only, no buffering)."""
    return StreamingResponse(cam_mjpeg(), media_type=f"multipart/x-mixed-replace; boundary={CAM_BOUNDARY}",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/camera.jpg")
def camera_jpg():
    if RELAY.jpeg is None:
        raise HTTPException(404, "No camera frames yet.")
    return Response(RELAY.jpeg, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Frame-Seq": str(RELAY.seq), "X-Frame-Ts": f"{RELAY.meta.get('ts', 0):.3f}"})


@app.get("/camera/status")
def camera_status():
    return {**RELAY.status(), "auto_grade": {"enabled": __import__("worn.autograde", fromlist=["x"]).ENABLED,
            "key": AUTO.key, "stroke": AUTO.stroke, "scores": AUTO.scores, "final_started": AUTO.final_started}}
