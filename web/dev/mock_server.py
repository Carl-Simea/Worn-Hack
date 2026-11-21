"""Worn mock backend for building /web without agent A's server (owner: agent B).

Stdlib only. Serves the pages the way the real backend does and fakes every endpoint in the
contract, including a DEMO loop that drives /live/state like the glasses would:

  stroke-by-stroke writing -> new ink observed -> stroke matched -> ... -> graded -> reaction -> confetti -> next char

    python3 web/dev/mock_server.py [--port 8090] [--no-demo]

It is a stand-in only: shapes follow the contract in the brief; where the brief gives no shape,
web/README.md documents the shape the pages accept (and the pages tolerate missing fields).
"""
from __future__ import annotations

import argparse
import json
import math
import mimetypes
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
CONTENT = ROOT / "content"
LANGS = ["mandarin", "japanese", "hindi", "arabic", "russian"]

ROUTES = {
    "/live": "live.html", "/mirror": "live.html", "/app": "app.html", "/app/journal": "journal.html",
    "/glasses": "glasses.html", "/": "app.html",
}


def load_content() -> dict:
    out = {}
    for l in LANGS:
        f = CONTENT / f"{l}.json"
        if f.exists():
            d = json.loads(f.read_text("utf-8"))
            for p in d["phrases"]:
                if p.get("audio") and not (CONTENT / p["audio"]).exists():
                    p["audio"] = None
                elif p.get("audio"):
                    p["audio"] = "/static/content/" + p["audio"]
            out[l] = d
    return out


def stroke_url(lang: str, ch: str) -> str | None:
    hexcp = "-".join(f"{ord(c):x}" for c in ch)
    for base, prefix in ((CONTENT / "strokes", "/static/content/strokes"), (WEB / "strokes", "/static/web/strokes")):
        for ext in ("json", "svg"):
            if (base / lang / f"{hexcp}.{ext}").exists():
                return f"{prefix}/{lang}/{hexcp}.{ext}"
    return None


def stroke_count(lang: str, ch: str) -> int:
    u = stroke_url(lang, ch)
    if not u:
        return max(2, min(6, len(ch) * 3))
    p = (CONTENT if u.startswith("/static/content") else WEB) / u.split("/", 3)[3]
    if u.endswith(".svg"):
        return max(1, len(re.findall(r"<path", p.read_text("utf-8"))))
    d = json.loads(p.read_text("utf-8"))
    return len(d.get("strokes") or [1])


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.content = load_content()
        self.session = None
        self.result = None
        self.version = 0
        self.glasses = {"connected": True, "showing": None, "phase": "idle", "stroke": 0, "stroke_count": 0}
        self.photo_ts = None
        self.photo_strokes = 0
        self.steps: list[dict] = []
        self.events: list[dict] = []
        self.latency = {"tier1": None, "tier2": None, "tier3": None}
        self.listening = False
        self.progress = {"streak": 3, "today": 0, "chars_learned": 11, "accuracy": 0.86}
        self.journal: dict[str, list] = {}
        self.seed_journal()

    def seed_journal(self):
        now = time.time()
        for lang, d in self.content.items():
            rows = []
            for p in d["phrases"][:3]:
                for ch in dict.fromkeys(p["chars"][:2]):
                    rows.append({"char": ch, "phrase_id": p["id"], "photos": [
                        {"url": photo_url(lang, ch, 0.35, seed=1), "ts": now - 6 * 86400, "score": 48, "day": 1},
                        {"url": photo_url(lang, ch, 0.7, seed=2), "ts": now - 3 * 86400, "score": 74, "day": 4},
                        {"url": photo_url(lang, ch, 1.0, seed=3), "ts": now - 600, "score": 93, "day": 7},
                    ]})
            self.journal[lang] = rows

    def step(self, text, kind="info", **extra):
        self.steps.append({"ts": time.time(), "text": text, "kind": kind, **extra})
        self.steps = self.steps[-40:]

    def event(self, type_, text):
        self.events.append({"ts": time.time(), "type": type_, "text": text})
        self.events = self.events[-40:]

    def set_session(self, lang, phrase_id, char_index=0, mode="write"):
        d = self.content[lang]
        p = next(x for x in d["phrases"] if x["id"] == phrase_id)
        ch = p["chars"][char_index]
        with self.lock:
            self.version += 1
            self.session = {
                "lang": lang, "lang_name": d["name"], "rtl": bool(d.get("rtl")), "phrase_id": p["id"],
                "text": p["text"], "char": ch, "char_index": char_index, "total_chars": len(p["chars"]),
                "romanization": p.get("romanization"), "meaning": p.get("meaning"), "audio_url": p.get("audio"),
                "stroke_url": stroke_url(lang, ch), "mode": mode, "version": self.version,
            }
            self.result = None
            n = stroke_count(lang, ch)
            self.glasses.update(showing=ch, phase="demo", stroke=1, stroke_count=n)
            self.photo_strokes = 0
            self.event("session", f"{d['name']}: {p['text']} · {ch} ({char_index + 1}/{len(p['chars'])})")
            self.step(f"new lesson: {ch} ({p.get('romanization')}), {n} strokes", "plan")
        return self.session

    def live(self):
        with self.lock:
            return {
                "session": self.session,
                "glasses": dict(self.glasses),
                "latest_photo_url": (photo_url(self.session["lang"], self.session["char"], self.photo_strokes / max(1, self.glasses["stroke_count"]), ts=self.photo_ts)
                                     if self.session and self.photo_ts else None),
                "last_result": self.result,
                "agent_steps": self.steps[-14:],
                "events": self.events[-14:],
                "latency": dict(self.latency),
                "progress": {**self.progress, "char_index": self.session["char_index"] if self.session else 0,
                             "total_chars": self.session["total_chars"] if self.session else 0},
                "listening": self.listening,
                "ts": time.time(),
            }


def photo_url(lang, ch, frac, seed=0, ts=None):
    return f"/mock/photo.svg?lang={lang}&c={quote(ch)}&f={frac:.2f}&s={seed}" + (f"&t={ts:.3f}" if ts else "")


def photo_svg(ch, frac, seed, lang):
    rnd = random.Random(f"{ch}{seed}")
    rot = rnd.uniform(-4, 4)
    wob = rnd.uniform(-6, 6)
    fam = {"mandarin": "Noto Serif SC", "japanese": "Noto Serif JP", "hindi": "Noto Serif Devanagari",
           "arabic": "Noto Naskh Arabic"}.get(lang, "Noto Serif")
    op = 0.25 + 0.75 * max(0.0, min(1.0, frac))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480">
<defs><radialGradient id="v" cx="50%" cy="45%" r="75%"><stop offset="0" stop-color="#f4efe4"/><stop offset="1" stop-color="#cfc6b4"/></radialGradient></defs>
<rect width="640" height="480" fill="#8d8473"/>
<g transform="rotate({rot:.1f} 320 240)"><rect x="70" y="30" width="500" height="430" fill="url(#v)"/>
<g stroke="#c9b9a0" stroke-width="2" fill="none"><rect x="170" y="90" width="300" height="300"/><path d="M320 90v300M170 240h300" stroke-dasharray="6 8"/></g>
<text x="{320 + wob:.0f}" y="245" font-family="{fam}, serif" font-size="230" text-anchor="middle" dominant-baseline="central"
 fill="#1d2433" fill-opacity="{op:.2f}" transform="skewX({rnd.uniform(-6, 6):.1f})">{ch}</text></g></svg>"""


class Demo(threading.Thread):
    """Drives the state like the glasses + tutor agent would."""

    def __init__(self, st: State):
        super().__init__(daemon=True)
        self.st = st

    def sleep(self, s):
        time.sleep(s)

    def run(self):
        plan = [(l, p["id"]) for l in LANGS for p in self.st.content[l]["phrases"][:2]]
        i = 0
        while True:
            lang, pid = plan[i % len(plan)]
            phrase = next(p for p in self.st.content[lang]["phrases"] if p["id"] == pid)
            for ci in range(len(phrase["chars"])):
                self.write_char(lang, pid, ci, attempt_fail=(ci == 1 and i % 3 == 1))
            i += 1

    def write_char(self, lang, pid, ci, attempt_fail=False):
        st = self.st
        s = st.set_session(lang, pid, ci)
        n = st.glasses["stroke_count"]
        st.listening = random.random() < 0.4
        self.sleep(2.2)
        for k in range(1, n + 1):
            with st.lock:
                st.glasses.update(phase="writing", stroke=k)
            self.sleep(1.1)
            t1 = random.randint(35, 120)
            with st.lock:
                st.photo_ts = time.time()
                st.photo_strokes = k
                st.latency["tier1"] = t1
                st.step("observed new ink", "observe")
                m = random.uniform(0.78, 0.97)
                st.step(f"stroke {k} matched {m:.2f}", "match", score=round(m, 2))
                if k < n:
                    st.step(f"advancing to stroke {k + 1}", "advance")
            self.sleep(0.5)
        with st.lock:
            st.glasses.update(phase="checking")
            st.step("whole character: asking vision grader", "grade")
            st.event("capture", "photo sent to grader")
        t2 = random.randint(700, 1600)
        self.sleep(t2 / 1000)
        score = random.randint(34, 52) if attempt_fail else random.randint(84, 98)
        ok = not attempt_fail
        t3 = random.randint(900, 2600)
        fb = (f"Clean {s['char']}! The proportions look right." if score >= 90 else f"Good {s['char']}, nicely readable.") if ok \
            else "Close! Make the last stroke longer and keep it straight."
        reaction = random.choice(["cheer", "drumroll", "applause"]) if ok else "encourage"
        line = {"cheer": "Woo-hoo! That one goes on the fridge.", "drumroll": "Ba-dum-tss. Nailed it.",
                "applause": "The crowd goes wild.", "encourage": "So close. One more go?"}[reaction]
        with st.lock:
            st.latency["tier2"] = t2
            st.step(f"graded {score}", "grade", score=score)
        self.sleep(t3 / 1000)
        with st.lock:
            st.latency["tier3"] = t3
            st.step(f"reaction: {reaction}", "react")
            st.result = {"correct": ok, "score": score, "feedback": fb, "reaction": reaction, "reaction_line": line,
                         "seen": s["char"] if ok else "", "char": s["char"], "lang": s["lang"], "ts": time.time(),
                         "latency_ms": t2 + t3, "image_url": photo_url(s["lang"], s["char"], 1.0, ts=st.photo_ts)}
            st.glasses.update(phase="celebrate" if ok else "retry")
            st.event("grade", f"{s['char']} {score}/100 · {reaction}")
            st.progress["today"] += 1 if ok else 0
            if ok:
                st.event("celebrate", "confetti on the glasses")
        self.sleep(4.2)
        if attempt_fail:  # second try succeeds
            self.write_char(s["lang"], s["phrase_id"], s["char_index"])


ST = State()


class H(BaseHTTPRequestHandler):
    server_version = "WornMock/1"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def file(self, p: Path):
        if not p.is_file():
            return self.send(404, {"detail": "not found"})
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".js":
            ctype = "text/javascript"
        self.send(200, p.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") else ""))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path.rstrip("/") or "/"
        if path in ROUTES:
            return self.file(WEB / ROUTES[path])
        if re.fullmatch(r"/print/\w+", path):
            return self.file(WEB / "print.html")
        if path.startswith("/static/web/"):
            return self.file(WEB / path[len("/static/web/"):])
        if path.startswith("/static/content/"):
            return self.file(CONTENT / path[len("/static/content/"):])
        if path == "/health":
            return self.send(200, {"ok": True, "mock": True, "langs": LANGS, "version": ST.version})
        if path == "/content":
            return self.send(200, {"langs": [ST.content[l] for l in LANGS if l in ST.content]})
        if path == "/session":
            return self.send(200, ST.session) if ST.session else self.send(404, {"detail": "no session"})
        if path == "/session/result":
            return self.send(200, ST.result) if ST.result else self.send(404, {"detail": "no result"})
        if path == "/live/state":
            return self.send(200, ST.live())
        if path == "/mock/photo.svg":
            return self.send(200, photo_svg(q.get("c", "?"), float(q.get("f", 1)), q.get("s", "0"), q.get("lang", "")), "image/svg+xml")
        if path == "/journal":
            lang = q.get("lang") or "mandarin"
            return self.send(200, {"lang": lang, "entries": ST.journal.get(lang, [])})
        if path == "/review":
            items = []
            for l in LANGS[:5]:
                p = ST.content[l]["phrases"][1]
                items.append({"lang": l, "phrase_id": p["id"], "char_index": 0, "char": p["chars"][0],
                              "reason": random.choice(["shaky last time", "not seen for 3 days", "new today"])})
            return self.send(200, {"items": items, "date": time.strftime("%Y-%m-%d")})
        if path == "/name":
            return self.send(200, mock_name(q.get("text", ""), q.get("lang")))
        return self.send(404, {"detail": "not found"})

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/session":
            try:
                d = json.loads(self.body() or b"{}")
                return self.send(200, ST.set_session(d["lang"], d["phrase_id"], int(d.get("char_index", 0)), d.get("mode", "write")))
            except (KeyError, StopIteration, IndexError) as e:
                return self.send(400, {"detail": f"bad session: {e}"})
        if u.path == "/grade":
            self.body()
            s = ST.session
            if not s:
                return self.send(400, {"detail": "no session"})
            r = {"correct": True, "score": random.randint(80, 97), "feedback": f"Nice {s['char']}!", "reaction": "cheer",
                 "seen": s["char"], "char": s["char"], "lang": s["lang"], "ts": time.time(), "latency_ms": 1200}
            with ST.lock:
                ST.result = r
                ST.photo_ts = time.time()
                ST.photo_strokes = ST.glasses["stroke_count"]
                ST.event("grade", f"{s['char']} {r['score']}/100")
            return self.send(200, r)
        if u.path == "/compose":
            d = json.loads(self.body() or b"{}")
            return self.send(200, mock_compose(d.get("text", ""), d.get("lang") or "mandarin"))
        return self.send(404, {"detail": "not found"})


def mock_compose(text, lang):
    t = text.lower()
    for p in ST.content[lang]["phrases"]:
        if p["meaning"].lower() in t or p["id"].replace("_", " ") in t:
            return {"lang": lang, "text": p["text"], "chars": p["chars"], "romanization": p["romanization"],
                    "meaning": p["meaning"], "phrase_id": p["id"], "source": text}
    p = ST.content[lang]["phrases"][1]
    return {"lang": lang, "text": p["text"], "chars": p["chars"], "romanization": p["romanization"],
            "meaning": p["meaning"], "phrase_id": p["id"], "source": text, "note": "mock: closest phrase"}


NAMES = {"mandarin": ("妮拉", ["妮", "拉"], "Nī lā"), "japanese": ("ニラ", ["ニ", "ラ"], "ni ra"),
         "hindi": ("नायला", ["ना", "य", "ला"], "nāyalā"), "arabic": ("نايلا", ["ن", "ا", "ي", "ل", "ا"], "nāylā"),
         "russian": ("Найла", ["Н", "а", "й", "л", "а"], "Nayla")}


def mock_name(text, lang):
    out = []
    for l in ([lang] if lang else LANGS):
        t, chars, rom = NAMES[l]
        out.append({"lang": l, "text": t, "chars": chars, "romanization": rom})
    return {"name": text, "results": out}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--no-demo", action="store_true")
    a = ap.parse_args()
    if not a.no_demo:
        Demo(ST).start()
    print(f"worn mock on http://127.0.0.1:{a.port}  (live: /live, app: /app)")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()
