"""Worn mock backend for building /web without agent A's server (owner: agent B).

Stdlib only. Serves the pages the way the real backend does and fakes every endpoint with the same
JSON shapes as backend/app.py (A), plus a DEMO loop that drives /live/state like the glasses would:

  watch the animation -> write stroke by stroke (tier 1 ink diff, tier 2 stroke match) -> checking
  (tier 3 vision + tutor agent) -> result + reaction -> next char

    python3 web/dev/mock_server.py [--port 8090] [--no-demo]
"""
from __future__ import annotations

import argparse
import itertools
import json
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
LANGS = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]
SCRIPT = {"mandarin": "Simplified Chinese", "hindi": "Devanagari", "arabic": "Arabic", "russian": "Cyrillic", "hebrew": "Hebrew", "greek": "Greek"}
ROUTES = {"/live": "live.html", "/mirror": "live.html", "/app": "app.html", "/app/journal": "journal.html",
          "/glasses": "glasses.html", "/": "app.html"}
IDS = itertools.count(1)


def load_content() -> dict:
    out = {}
    for l in LANGS:
        f = CONTENT / f"{l}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text("utf-8"))
        items = d.get("items") or d.get("phrases") or []
        for p in items:
            a = p.get("audio")
            p["audio_url"] = f"/static/content/{a}" if a and (CONTENT / a).exists() else None
            p["char_info"] = [{"char": c, "stroke_count": stroke_count(l, c), "stroke_url": stroke_url(l, c)} for c in p.get("chars") or []]
        d.update(items=items, phrases=items, script=d.get("script") or SCRIPT[l])
        out[l] = d
    return out


def stroke_url(lang: str, ch: str) -> str | None:
    hexcp = "-".join(f"{ord(c):x}" for c in ch)
    for ext in ("json", "svg"):
        if (CONTENT / "strokes" / lang / f"{hexcp}.{ext}").exists():
            return f"/static/content/strokes/{lang}/{hexcp}.{ext}"
    return None


def stroke_count(lang: str, ch: str) -> int:
    u = stroke_url(lang, ch)
    if not u:
        return 1
    p = CONTENT / u.split("/static/content/", 1)[1]
    if u.endswith(".svg"):
        return max(1, len(re.findall(r"<path", p.read_text("utf-8"))))
    return len(json.loads(p.read_text("utf-8")).get("strokes") or [1])


def photo_url(lang, ch, frac, seed=0, ts=None):
    return f"/mock/photo.svg?lang={lang}&c={quote(ch)}&f={frac:.2f}&s={seed}" + (f"&t={ts:.3f}" if ts else "")


def photo_svg(ch, frac, seed, lang):
    rnd = random.Random(f"{ch}{seed}")
    rot, wob = rnd.uniform(-4, 4), rnd.uniform(-6, 6)
    fam = {"mandarin": "Noto Serif SC", "hindi": "Noto Serif Devanagari", "arabic": "Noto Naskh Arabic",
           "hebrew": "Noto Serif Hebrew"}.get(lang, "Noto Serif")
    op = 0.25 + 0.75 * max(0.0, min(1.0, frac))
    size = 230 if len(ch) <= 2 else int(520 / len(ch))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480">
<defs><radialGradient id="v" cx="50%" cy="45%" r="75%"><stop offset="0" stop-color="#f4efe4"/><stop offset="1" stop-color="#cfc6b4"/></radialGradient></defs>
<rect width="640" height="480" fill="#8d8473"/>
<g transform="rotate({rot:.1f} 320 240)"><rect x="70" y="30" width="500" height="430" fill="url(#v)"/>
<g stroke="#c9b9a0" stroke-width="2" fill="none"><rect x="170" y="90" width="300" height="300"/><path d="M320 90v300M170 240h300" stroke-dasharray="6 8"/></g>
<text x="{320 + wob:.0f}" y="245" font-family="{fam}, serif" font-size="{size}" text-anchor="middle" dominant-baseline="central"
 fill="#1d2433" fill-opacity="{op:.2f}" transform="skewX({rnd.uniform(-6, 6):.1f})">{ch}</text></g></svg>"""


class Live:
    def __init__(self):
        self.lock = threading.RLock()
        self.content = load_content()
        self.reset()
        self.journal: list[dict] = []
        self.seed_journal()

    def reset(self):
        self.version = 0
        self.session = None
        self.result = None
        self.next = None
        self.glasses = {"connected": True, "showing": "idle", "phase": "idle", "stroke": 0, "stroke_count": 0, "last_seen": time.time()}
        self.photo = None
        self.listening = False
        self.events: list[dict] = []
        self.steps: list[dict] = []
        self.lat = {"tier1": [], "tier2": [], "tier3": [], "decide": [], "grade": []}
        self.tries = 0

    def seed_journal(self):
        now = time.time()
        for lang, d in self.content.items():
            for it in d["items"][:3]:
                for ci, ch in enumerate(it["chars"][:2]):
                    for days, frac, score in ((6, .35, 41), (3, .7, 72), (0.01, 1, 94)):
                        self.journal.append({"lang": lang, "item_id": it["id"], "char_index": ci, "char": ch, "score": score,
                                             "correct": score >= 60, "feedback": "", "seen": ch, "mode": "write",
                                             "image_url": photo_url(lang, ch, frac, seed=days), "ts": now - days * 86400})

    def bump(self):
        self.version += 1

    def event(self, type_, data=None):
        self.events.append({"id": next(IDS), "ts": time.time(), "type": type_, "data": data or {}})
        self.events = self.events[-60:]
        self.bump()

    def step(self, run_id, phase, summary, tool=None, ms=None, model=None, data=None):
        self.steps.append({"id": next(IDS), "run_id": run_id, "ts": time.time(), "phase": phase, "tool": tool,
                           "summary": summary, "ms": None if ms is None else int(ms), "model": model, "status": "ok", "data": data})
        self.steps = self.steps[-80:]
        self.bump()

    def latency(self, tier, ms):
        self.lat[tier] = (self.lat[tier] + [ms])[-50:]
        self.bump()

    def item(self, lang, iid):
        return next(x for x in self.content[lang]["items"] if x["id"] == iid)

    def set_session(self, lang, iid, char_index=0, mode="write", item=None):
        d = self.content[lang]
        it = item or self.item(lang, iid)
        ch = it["chars"][char_index]
        n = stroke_count(lang, ch)
        dictation = mode == "dictation"
        with self.lock:
            self.session = {
                "lang": lang, "lang_name": d["name"], "script": d.get("script"), "rtl": bool(d.get("rtl")),
                "item_id": it["id"], "phrase_id": it["id"],
                "item": {k: it.get(k) for k in ("id", "text", "chars", "romanization", "meaning")},
                "text": it["text"], "char": ch, "char_index": char_index, "total_chars": len(it["chars"]),
                "romanization": it.get("romanization"), "char_romanization": None, "meaning": it.get("meaning"),
                "audio_url": it.get("audio_url"), "stroke_url": stroke_url(lang, ch), "stroke_count": n, "stroke_index": 0,
                "stroke_order": "true" if stroke_url(lang, ch) else "trace", "mode": mode, "show_char": not dictation,
                "prompt": "Listen, then write what you hear." if dictation else "Watch, then write it on paper.",
                "back_translation": it.get("back_translation"), "note": it.get("note"),
            }
            self.result = None
            self.next = None
            self.glasses.update(showing="stroke_animation" if not dictation else "audio_prompt", phase="watch", stroke=0, stroke_count=n)
            self.bump()
            self.session["version"] = self.version
            self.event("session", {"lang": lang, "item_id": it["id"], "char": ch, "char_index": char_index, "mode": mode})
        return self.session

    def lat_out(self, t):
        v = self.lat[t]
        if not v:
            return {"last_ms": None, "avg_ms": None, "p95_ms": None, "n": 0}
        s = sorted(v)
        return {"last_ms": int(v[-1]), "avg_ms": int(sum(v) / len(v)), "p95_ms": int(s[min(len(s) - 1, int(.95 * len(s)))]), "n": len(v)}

    def progress(self):
        s = self.session
        if not s:
            return {}
        items = self.content[s["lang"]]["items"]
        ids = [i["id"] for i in items]
        learned = {e["char"] for e in self.journal if e["lang"] == s["lang"] and e["correct"]}
        allc = {c for i in items for c in i["chars"]}
        return {"lang": s["lang"], "item_id": s["item_id"], "item_index": ids.index(s["item_id"]) if s["item_id"] in ids else None,
                "items_total": len(ids), "items_done": 1, "char_index": s["char_index"], "chars_total": s["total_chars"],
                "learned": len(learned & allc), "learnable": len(allc),
                "attempts": sum(1 for e in self.journal if e["lang"] == s["lang"])}

    def snapshot(self):
        with self.lock:
            return {"version": self.version, "ts": time.time(), "session": self.session, "glasses": dict(self.glasses),
                    "latest_photo_url": self.photo, "last_result": self.result, "next": self.next,
                    "agent_steps": self.steps[-40:], "events": self.events[-30:],
                    "latency": {t: self.lat_out(t) for t in self.lat}, "progress": self.progress(),
                    "listening": self.listening, "tries": self.tries}

    def choose_next(self, s, correct):
        items = self.content[s["lang"]]["items"]
        if not correct:
            return {"lang": s["lang"], "item_id": s["item_id"], "char_index": s["char_index"], "char": s["char"], "action": "retry", "reason": "try again"}
        if s["char_index"] + 1 < s["total_chars"]:
            return {"lang": s["lang"], "item_id": s["item_id"], "char_index": s["char_index"] + 1,
                    "char": s["item"]["chars"][s["char_index"] + 1], "action": "advance", "reason": "next in the word"}
        ids = [i["id"] for i in items]
        k = (ids.index(s["item_id"]) + 1) % len(ids) if s["item_id"] in ids else 0
        return {"lang": s["lang"], "item_id": items[k]["id"], "char_index": 0, "char": items[k]["chars"][0], "action": "advance", "reason": "next word"}

    def grade(self, correct=None, photo=None, run_id=None):
        """Tier 3 + tutor agent result, with the same keys as backend/worn/agent.py."""
        s = self.session
        run_id = run_id or f"r{next(IDS)}"
        if correct is None:
            correct = random.random() > 0.2
        score = random.randint(84, 98) if correct else random.randint(30, 52)
        mood = random.choice(["celebrate", "proud"]) if correct else random.choice(["encourage", "gentle"])
        line = {"celebrate": random.choice(["Beautiful, you got it!", "That one goes on the fridge!", "Nailed it!"]),
                "proud": "Yes! Nicely done.", "encourage": "Almost! Make the last stroke longer.",
                "gentle": "Let's watch it once more."}[mood]
        fb = (f"Nice! That's {s['char']}." if score < 92 else f"Clean {s['char']}. Great proportions.") if correct \
            else "Close! The last stroke should reach further down."
        nxt = self.choose_next(s, correct)
        with self.lock:
            self.tries = 0 if correct else self.tries + 1
            self.result = {"correct": correct, "score": score, "feedback": fb, "reaction": line, "mood": mood,
                           "emoji": {"celebrate": "🎉", "proud": "✨", "encourage": "💪", "gentle": "👀"}[mood],
                           "sound": "success" if correct else "retry", "seen": s["char"] if correct else "",
                           "template_score": random.randint(60, 95), "char": s["char"], "lang": s["lang"],
                           "item_id": s["item_id"], "char_index": s["char_index"], "image_url": photo or self.photo,
                           "next": nxt, "tries": self.tries,
                           "agent": {"run_id": run_id, "decided_by": "qwen2.5:7b", "fallback": False,
                                     "thought": "Clear match, move on." if correct else "Last stroke too short.",
                                     "action": nxt["action"], "steps": 6},
                           "latency_ms": random.randint(1400, 3200), "tier3_ms": random.randint(700, 1500), "ts": time.time()}
            self.next = nxt
            self.glasses.update(showing="result", phase="result")
            self.journal.append({"lang": s["lang"], "item_id": s["item_id"], "char_index": s["char_index"], "char": s["char"],
                                 "score": score, "correct": correct, "feedback": fb, "seen": s["char"], "mode": s["mode"],
                                 "image_url": photo or self.photo, "ts": time.time()})
            self.bump()
        return self.result


class Demo(threading.Thread):
    def __init__(self, st: Live):
        super().__init__(daemon=True)
        self.st = st

    def run(self):
        st = self.st
        plan = [(l, it["id"]) for l in LANGS if l in st.content for it in st.content[l]["items"][:2]]
        i = 0
        while True:
            lang, iid = plan[i % len(plan)]
            it = st.item(lang, iid)
            for ci in range(len(it["chars"])):
                if ci >= 3:
                    break  # keep the loop moving between scripts
                self.write_char(lang, iid, ci, fail_first=(ci == 1 and i % 3 == 1))
            i += 1

    def write_char(self, lang, iid, ci, fail_first=False):
        st = self.st
        s = st.set_session(lang, iid, ci)
        n = s["stroke_count"]
        st.listening = random.random() < 0.4
        time.sleep(2.4)
        for k in range(n):
            with st.lock:
                st.glasses.update(phase="write", stroke=k)
                st.bump()
            time.sleep(1.0)
            t1, t2 = random.randint(18, 60), random.randint(8, 30)
            with st.lock:
                st.photo = photo_url(lang, s["char"], (k + 1) / n, ts=time.time())
                st.event("photo", {"url": st.photo})
                st.latency("tier1", t1)
                st.step("t1", "observe", f"New ink in the box ({random.randint(3, 14)}% of the cell)", tool="ink_diff", ms=t1)
                st.latency("tier2", t2)
                sc = random.randint(72, 97)
                st.step("t2", "evaluate", f"Stroke {k + 1}/{n}: {sc}/100 done", tool="compare_to_template", ms=t2,
                        data={"score": sc, "done": True, "stroke_index": k, "stroke_count": n})
                if k + 1 < n:
                    st.glasses.update(stroke=k + 1)
                    st.event("stroke", {"stroke": k + 1, "stroke_count": n})
            time.sleep(0.4)
        run = f"r{next(IDS)}"
        with st.lock:
            st.glasses.update(phase="checking", showing="checking")
            st.step(run, "observe", "Photo of the whole character", tool="capture", ms=random.randint(80, 200))
            st.event("capture", {"char": s["char"]})
        t3 = random.randint(700, 1500)
        time.sleep(t3 / 1000)
        ok = not fail_first
        with st.lock:
            st.latency("tier3", t3)
            st.step(run, "evaluate", f"Vision read {s['char'] if ok else '?'}: {'match' if ok else 'not yet'}",
                    tool="read_handwriting", ms=t3, model="qwen2.5vl:7b")
            st.step(run, "evaluate", f"Template overlap {random.randint(62, 95)}/100", tool="compare_to_template", ms=random.randint(40, 120))
        time.sleep(0.6)
        with st.lock:
            dms = random.randint(500, 1400)
            st.latency("decide", dms)
            st.latency("grade", t3 + dms + 200)
            st.step(run, "decide", ("ADVANCE: clean match" if ok else "RETRY: last stroke too short"), ms=dms, model="qwen2.5:7b")
        time.sleep(0.5)
        r = st.grade(correct=ok, photo=photo_url(lang, s["char"], 1.0, ts=time.time()), run_id=run)
        with st.lock:
            st.step(run, "act", f"Next: {r['next']['char']} ({r['next']['reason']})", tool="choose_next_item", ms=3)
            st.step(run, "act", f"{r['emoji']} \"{r['reaction']}\"", tool="react", ms=2)
            st.event("grade", {"char": s["char"], "score": r["score"], "correct": ok, "mood": r["mood"]})
            if ok:
                st.event("celebrate", {"mood": r["mood"]})
        time.sleep(4.0)
        if fail_first:
            self.write_char(lang, iid, ci)


ST = Live()


def mock_compose(text, lang):
    t = (text or "").lower()
    items = ST.content[lang]["items"]
    pick = next((p for p in items if p.get("meaning", "").lower() in t), None) or items[1]
    return {"native": pick["text"], "romanization": pick.get("romanization"), "back_translation": pick.get("meaning"),
            "chars": pick["chars"], "lang": lang, "text": text, "note": f"{len(pick['chars'])} characters to write."}


def mock_name(text):
    return {"devanagari": "नायला", "arabic": "نايلا", "cyrillic": "Найла", "hebrew": "נאילה", "greek": "Νάιλα", "text": text,
            "note": "Names are written by sound, so these spellings are approximate.", "model": "mock"}


class H(BaseHTTPRequestHandler):
    server_version = "WornMock/2"

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
            return self.send(200, {"ok": True, "mock": True, "langs": LANGS, "version": ST.version, "glasses": ST.glasses})
        if path == "/content":
            return self.send(200, {"langs": [ST.content[l] for l in LANGS if l in ST.content]})
        if path == "/session":
            return self.send(200, ST.session) if ST.session else self.send(404, {"detail": "No lesson yet. Pick one on the phone."})
        if path == "/session/result":
            return self.send(200, ST.result) if ST.result else self.send(404, {"detail": "No result yet for this character."})
        if path == "/live/state":
            if q.get("since") and int(q["since"]) == ST.version:
                return self.send(200, {"unchanged": True, "version": ST.version})
            return self.send(200, ST.snapshot())
        if path == "/mock/photo.svg":
            return self.send(200, photo_svg(q.get("c", "?"), float(q.get("f", 1)), q.get("s", "0"), q.get("lang", "")), "image/svg+xml")
        if path == "/journal":
            lang = q.get("lang")
            es = [e for e in ST.journal if not lang or e["lang"] == lang][::-1]
            chars = {}
            for e in es:
                c = chars.setdefault(f"{e['lang']}:{e['char']}", {"lang": e["lang"], "char": e["char"], "attempts": 0, "correct": 0, "best": 0, "last_ts": e["ts"]})
                c["attempts"] += 1
                c["correct"] += 1 if e["correct"] else 0
                c["best"] = max(c["best"], e["score"])
            return self.send(200, {"lang": lang, "entries": es, "chars": list(chars.values()), "total": len(es),
                                   "correct": sum(1 for e in es if e["correct"])})
        if path == "/review":
            items = []
            for l in [x for x in LANGS if x in ST.content][:5]:
                it = ST.content[l]["items"][1]
                items.append({"lang": l, "item_id": it["id"], "char_index": 0, "char": it["chars"][0], "meaning": it.get("meaning"),
                              "romanization": it.get("romanization"), "reason": random.choice(["missed 1 of 3 tries", "learned, keep it fresh", "new today"]),
                              "weakness": 0.4, "stats": None})
            return self.send(200, {"title": "Daily 5", "items": items, "count": 5, "message": "Five quick characters to keep them fresh."})
        if path == "/name":
            return self.send(200, mock_name(q.get("text", "")))
        if path == "/capture/latest":
            return self.send(404, {"detail": "No photos yet."})
        return self.send(404, {"detail": "not found"})

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/session":
            d = json.loads(self.body() or b"{}")
            try:
                if d.get("mode") == "compose" and d.get("text"):
                    c = mock_compose(d["text"], d["lang"])
                    item = {"id": f"compose-{next(IDS)}", "text": c["native"], "chars": c["chars"], "romanization": c["romanization"],
                            "meaning": d["text"], "back_translation": c["back_translation"], "note": c["note"], "audio_url": None}
                    return self.send(200, ST.set_session(d["lang"], item["id"], 0, "compose", item=item))
                iid = d.get("item_id") or d.get("phrase_id")
                return self.send(200, ST.set_session(d["lang"], iid, int(d.get("char_index", 0)), d.get("mode", "write")))
            except (KeyError, StopIteration, IndexError) as e:
                return self.send(400, {"detail": f"bad session: {e}"})
        if u.path == "/session/next":
            n, s = ST.next, ST.session
            if not n or not s:
                return self.send(409, {"detail": "Nothing to move to yet. Write a character first."})
            return self.send(200, ST.set_session(n["lang"], n["item_id"], n["char_index"], s.get("mode", "write")))
        if u.path == "/grade":
            self.body()
            if not ST.session:
                return self.send(400, {"detail": "I need to know which character this is. Start a lesson first."})
            time.sleep(1.2)
            return self.send(200, ST.grade())
        if u.path == "/compose":
            d = json.loads(self.body() or b"{}")
            time.sleep(0.8)
            return self.send(200, mock_compose(d.get("text", ""), d.get("lang") or "mandarin"))
        if u.path == "/event":
            d = json.loads(self.body() or b"{}")
            with ST.lock:
                if d.get("type") in ("listening_start", "listening_stop"):
                    ST.listening = d["type"] == "listening_start"
                ST.event(d.get("type", "event"), d.get("data"))
            return self.send(200, {"ok": True, "version": ST.version})
        if u.path == "/reset":
            with ST.lock:
                ST.reset()
            return self.send(200, {"ok": True})
        return self.send(404, {"detail": "not found"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--no-demo", action="store_true")
    a = ap.parse_args()
    if not a.no_demo:
        Demo(ST).start()
    print(f"worn mock on http://127.0.0.1:{a.port}  (live: /live, app: /app)")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()
