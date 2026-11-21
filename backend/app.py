"""Worn backend (agent A).

One shared session lives in memory: the phone sets it, the glasses read it,
the glasses post a photo to /grade, the phone reads the result.

Run:  cd backend && uv run uvicorn app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

log = logging.getLogger("worn")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTENT_DIR = Path(os.environ.get("WORN_CONTENT_DIR", ROOT / "content"))
WEB_DIR = Path(os.environ.get("WORN_WEB_DIR", ROOT / "web"))
SEED_DIR = HERE / "seed"
CAPTURE_DIR = HERE / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

OLLAMA_URL = os.environ.get("WORN_OLLAMA_URL", "http://127.0.0.1:11434")
VISION_MODEL = os.environ.get("WORN_VISION_MODEL", "qwen2.5vl:7b")
GRADE_TIMEOUT = float(os.environ.get("WORN_GRADE_TIMEOUT", "45"))
# Demo safety net only: if the model is down, return a canned pass instead of an error.
FAKE_GRADE = os.environ.get("WORN_FAKE_GRADE") == "1"

LANG_ORDER = ["mandarin", "hindi", "arabic", "russian", "japanese", "asl"]
LANG_NAMES = {
    "mandarin": "Mandarin Chinese (simplified hanzi)",
    "hindi": "Hindi (Devanagari)",
    "arabic": "Arabic",
    "russian": "Russian (Cyrillic)",
    "japanese": "Japanese",
}

app = FastAPI(title="Worn")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Raw content files (audio, stroke animations, ASL videos) under /static/content/...
if CONTENT_DIR.is_dir():
    app.mount("/static/content", StaticFiles(directory=CONTENT_DIR), name="content")
if WEB_DIR.is_dir():
    app.mount("/static/web", StaticFiles(directory=WEB_DIR), name="web")


# ---------------------------------------------------------------- content

def load_content() -> dict[str, dict]:
    """content/{lang}.json (owned by C) wins; backend/seed/ is a fallback so mandarin always works."""
    langs: dict[str, dict] = {}
    for d in (SEED_DIR, CONTENT_DIR):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                langs[data["lang"]] = data
            except Exception as e:  # bad file from a teammate shouldn't take the server down
                log.warning("skipping %s: %s", f, e)
    return langs


def ordered(langs: dict[str, dict]) -> list[dict]:
    rank = {k: i for i, k in enumerate(LANG_ORDER)}
    return sorted(langs.values(), key=lambda l: rank.get(l["lang"], 99))


def find_phrase(lang: str, phrase_id: str) -> tuple[dict, dict]:
    langs = load_content()  # re-read every time so C's edits show up without a restart
    if lang not in langs:
        raise HTTPException(404, f"unknown lang {lang!r}; have {sorted(langs)}")
    for p in langs[lang]["phrases"]:
        if p["id"] == phrase_id:
            return langs[lang], p
    raise HTTPException(404, f"unknown phrase {phrase_id!r} for {lang}")


def static_url(rel: str | None) -> str | None:
    if not rel:
        return None
    if rel.startswith(("http://", "https://", "/")):
        return rel
    return f"/static/content/{rel}" if (CONTENT_DIR / rel).exists() else None


def stroke_url(lang: str, phrase: dict, char: str | None) -> str | None:
    """Convention with C: content/strokes/{lang}/{codepoint hex}.{svg|gif|webm|mp4|json}.
    Falls back to a per-phrase 'strokes' list if the lesson JSON provides one."""
    if not char:
        return None
    hexcp = "-".join(f"{ord(c):x}" for c in char)
    for ext in ("svg", "gif", "webm", "mp4", "json"):
        rel = f"strokes/{lang}/{hexcp}.{ext}"
        if (CONTENT_DIR / rel).exists():
            return f"/static/content/{rel}"
    return None


# ---------------------------------------------------------------- state

class SessionIn(BaseModel):
    lang: str
    phrase_id: str
    char_index: int = 0
    mode: Literal["write", "asl"] = "write"


_lock = threading.Lock()
_session: dict | None = None
_result: dict | None = None
_version = 0  # bumps on every change; clients can poll cheaply


def build_session(s: SessionIn) -> dict:
    lesson, p = find_phrase(s.lang, s.phrase_id)
    chars = p.get("chars") or []
    if s.mode == "write" and not chars:
        raise HTTPException(400, "phrase has no chars to write")
    if chars and not 0 <= s.char_index < len(chars):
        raise HTTPException(400, f"char_index must be 0..{len(chars) - 1}")
    char = chars[s.char_index] if chars else None
    return {
        "lang": s.lang,
        "lang_name": lesson.get("name", s.lang),
        "rtl": bool(lesson.get("rtl")),
        "phrase_id": p["id"],
        "text": p.get("text"),
        "char": char,
        "char_index": s.char_index,
        "total_chars": len(chars),
        "romanization": p.get("romanization"),
        "meaning": p.get("meaning"),
        "audio_url": static_url(p.get("audio")),
        "stroke_url": stroke_url(s.lang, p, char) if s.mode == "write" else None,
        "asl_url": static_url(p.get("asl")),
        "mode": s.mode,
    }


# ---------------------------------------------------------------- grading

PROMPT = """Look at this photo of handwriting on paper, taken from smart glasses (may be tilted or blurry).

Step 1: Read it. What {lang_name} character/letter is actually written? Answer with the character itself, exactly as you read it, even if it is not the one the learner wanted.
Step 2: The learner (an American beginner) was TRYING to write "{char}"{extra}. Compare what you read with "{char}".

Reply with JSON only:
{{"seen": "the character you read, or empty if no writing", "score": 0-100, "fix": "if it is not a clean {char}: the ONE most important fix in plain English, max 12 words, otherwise empty"}}

Score 90-100 for a clear {char}, 60-89 for a recognizable but messy {char}, under 40 if it is a different character or unreadable."""


def prep_image(raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1024, 1024))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


def parse_grade(text: str, char: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0) if m else text)
    seen = str(data.get("seen") or "").strip()
    score = int(max(0, min(100, float(data.get("score") or 0))))
    fix = str(data.get("fix") or "").strip().splitlines()[0][:120] if data.get("fix") else ""
    if not seen:
        return {"correct": False, "score": 0, "seen": "",
                "feedback": "I can't see your writing, hold the paper closer."}
    # The model's reading is the ground truth for "correct"; its score alone is too generous.
    correct = char in seen and score >= 60
    if not correct:
        score = min(score, 45)
        if not fix:
            fix = f"That looks like {seen}, not {char}. Watch the animation again."
    feedback = ("Nice! That's " + char + "." if score >= 85 else "Good, " + char + " is readable.") if correct else fix
    return {"correct": correct, "score": score, "seen": seen, "feedback": feedback}


async def run_grader(jpeg: bytes, char: str, lang: str, sess: dict | None) -> dict:
    extra = ""
    if sess and sess.get("char") == char:
        bits = [b for b in (sess.get("romanization") and f'romanized "{sess["romanization"]}"',
                            sess.get("meaning") and f'from the phrase meaning "{sess["meaning"]}"') if b]
        extra = f" ({', '.join(bits)})" if bits else ""
    prompt = PROMPT.format(lang_name=LANG_NAMES.get(lang, lang), char=char, extra=extra)
    body = {
        "model": VISION_MODEL,
        "prompt": prompt,
        "images": [base64.b64encode(jpeg).decode()],
        "format": "json",
        "stream": False,
        "keep_alive": "2h",
        "options": {"temperature": 0.1},
    }
    async with httpx.AsyncClient(timeout=GRADE_TIMEOUT) as c:
        r = await c.post(f"{OLLAMA_URL}/api/generate", json=body)
        r.raise_for_status()
        return parse_grade(r.json().get("response", ""), char)


# ---------------------------------------------------------------- routes

@app.on_event("startup")
async def warm_model() -> None:
    """Load the vision model into memory so the first demo grade isn't a 20s cold start."""
    def _warm():
        try:
            httpx.post(f"{OLLAMA_URL}/api/generate",
                       json={"model": VISION_MODEL, "prompt": "", "keep_alive": "2h"}, timeout=120)
            log.info("vision model %s warm", VISION_MODEL)
        except Exception as e:
            log.warning("could not warm %s at %s: %s", VISION_MODEL, OLLAMA_URL, e)
    threading.Thread(target=_warm, daemon=True).start()


@app.get("/health")
async def health():
    model_ok = False
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            tags = (await c.get(f"{OLLAMA_URL}/api/tags")).json()
            model_ok = any(m.get("name") == VISION_MODEL for m in tags.get("models", []))
    except Exception:
        pass
    return {"ok": True, "model": VISION_MODEL, "model_ready": model_ok, "fake_grade": FAKE_GRADE,
            "langs": [l["lang"] for l in ordered(load_content())], "version": _version}


@app.get("/content")
def content():
    return {"langs": ordered(load_content())}


@app.post("/session")
def set_session(s: SessionIn):
    global _session, _result, _version
    new = build_session(s)
    with _lock:
        _version += 1
        new["version"] = _version
        _session, _result = new, None
    log.info("session %s/%s char %s (%s)", s.lang, s.phrase_id, s.char_index, s.mode)
    return new


@app.get("/session")
def get_session():
    if _session is None:
        raise HTTPException(404, "no session yet; phone must POST /session")
    return _session


@app.post("/grade")
async def grade(image: UploadFile = File(...), char: str | None = Form(None), lang: str | None = Form(None)):
    global _result, _version
    sess = _session
    char = char or (sess and sess.get("char"))
    lang = lang or (sess and sess.get("lang"))
    if not char or not lang:
        raise HTTPException(400, "need char and lang (form fields, or an active session)")
    raw = await image.read()
    if not raw:
        raise HTTPException(400, "empty image")
    try:
        jpeg = prep_image(raw)
    except Exception as e:
        raise HTTPException(400, f"not an image: {e}")

    stamp = time.strftime("%H%M%S")
    (CAPTURE_DIR / f"{stamp}_{lang}_{ord(char[0]):x}.jpg").write_bytes(jpeg)

    t0 = time.time()
    try:
        res = await run_grader(jpeg, char, lang, sess)
    except Exception as e:
        log.error("grader failed: %r", e)
        if FAKE_GRADE:
            res = {"correct": True, "score": 80, "feedback": "Nice work, keep going!"}
        else:
            raise HTTPException(503, f"grader unavailable: {e}")
    res = {**res, "char": char, "lang": lang, "ts": time.time(), "latency_ms": int((time.time() - t0) * 1000)}
    log.info("grade %s %s -> %s", lang, char, res)
    with _lock:
        _result = res
        _version += 1
    return res


@app.get("/session/result")
def get_result():
    if _result is None:
        raise HTTPException(404, "no result yet for this session")
    return _result


@app.get("/glasses", response_class=HTMLResponse)
def glasses_page():
    """C owns web/glasses.html; serve it if present, else the minimal fallback in backend/."""
    for p in (WEB_DIR / "glasses.html", WEB_DIR / "glasses" / "index.html", HERE / "glasses_fallback.html"):
        if p.exists():
            return FileResponse(p, media_type="text/html")
    raise HTTPException(404)
