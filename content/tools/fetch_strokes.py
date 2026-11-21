"""Fetch standard stroke data for every Mandarin char used in the lessons, and prune unused files.
   python3 -I content/tools/fetch_strokes.py
Mandarin: hanzi-writer-data 2.0.1 (jsdelivr) -> strokes/mandarin/{hex}.json
(Hindi, Arabic, Russian, Hebrew and Greek are hand-authored in strokes_authored.py.)
"""
import json, sys, urllib.parse, urllib.request
from pathlib import Path

C = Path(__file__).resolve().parent.parent


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def chars_of(lang):
    d = json.loads((C / f"{lang}.json").read_text(encoding="utf-8"))
    return sorted({c for p in d["phrases"] for c in p["chars"]})


def prune(lang, keep):
    for f in (C / "strokes" / lang).glob("*"):
        if f.stem not in keep:
            f.unlink(); print("pruned", f.relative_to(C))


zh = chars_of("mandarin")
(C / "strokes/mandarin").mkdir(parents=True, exist_ok=True)
for c in zh:
    out = C / f"strokes/mandarin/{ord(c):x}.json"
    if out.exists() and "--force" not in sys.argv:
        continue
    d = json.loads(get("https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0.1/" + urllib.parse.quote(c) + ".json"))
    assert all(isinstance(s, str) for s in d["strokes"]) and len(d["strokes"]) == len(d["medians"])
    out.write_text(json.dumps({"strokes": d["strokes"], "medians": d["medians"], "radStrokes": d.get("radStrokes", [])},
                              separators=(",", ":")))
    print("zh", c, len(d["strokes"]), "strokes")
prune("mandarin", {f"{ord(c):x}" for c in zh})
