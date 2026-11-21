"""End-to-end content check against a running backend: every character of every item must get a session with
a stroke file (true order), audio, and per-char romanization; also checks names/, reactions, milestones, sfx.
   python3 content/tools/check_content.py [http://127.0.0.1:8000]
It POSTs /session, so it changes what the glasses show: don't run it during the demo."""
import json, sys, urllib.request
from pathlib import Path

B = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
C = Path(__file__).resolve().parent.parent


def req(path, body=None):
    r = urllib.request.Request(B + path, data=json.dumps(body).encode() if body else None,
                               headers={"content-type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as f:
        return json.load(f)


def ok(url):
    try:
        with urllib.request.urlopen(B + url, timeout=10) as f:
            return f.status == 200
    except Exception:
        return False


bad, n, items = [], 0, 0
content = req("/content")
langs = [L["lang"] for L in content["langs"]]
for L in content["langs"]:
    if not L.get("hero"):
        bad.append((L["lang"], "-", "-", ["no hero"]))
    for it in L.get("items") or L["phrases"]:
        items += 1
        for f in ("how", "why", "dictation"):
            if not it.get(f):
                bad.append((L["lang"], it["id"], "-", [f"no {f}"]))
        for i, ch in enumerate(it["chars"]):
            s = req("/session", {"lang": L["lang"], "item_id": it["id"], "char_index": i}); n += 1
            p = []
            if s.get("char") != ch: p.append("wrong char")
            if not s.get("stroke_url"): p.append("no stroke_url")
            elif not ok(s["stroke_url"]): p.append("stroke 404")
            if not s.get("audio_url") or not ok(s["audio_url"]): p.append("audio")
            if not s.get("char_romanization"): p.append("no char_romanization")
            if s.get("stroke_order") == "trace": p.append("no stroke order (trace)")
            if p: bad.append((L["lang"], it["id"], ch, p))
for f in ("reactions.json", "milestones.json"):
    d = json.loads((C / f).read_text(encoding="utf-8"))
    if f == "reactions.json":
        for k, v in d.items():
            if not k.startswith("_") and not ok(f"/static/content/sfx/{v['sound']}.wav"):
                bad.append((f, k, "-", ["sound 404"]))
    else:
        for lang in langs:
            if lang not in d: bad.append((f, lang, "-", ["missing language"]))
for f in (C / "names").glob("*.json"):
    if not ok(f"/static/content/names/{f.name}"): bad.append(("names", f.name, "-", ["404"]))
print(f"{len(langs)} languages, {items} items, {n} sessions; {len(bad)} problems")
for b in bad: print("  ", b)
sys.exit(1 if bad else 0)
