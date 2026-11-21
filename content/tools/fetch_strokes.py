"""Fetch standard stroke data for every Mandarin/Japanese char used in the lessons, and prune unused files.
   python3 -I content/tools/fetch_strokes.py
Mandarin: hanzi-writer-data 2.0.1 (jsdelivr) -> strokes/mandarin/{hex}.json
Japanese: KanjiVG (GitHub)                  -> strokes/japanese/{hex}.svg (clean copy, stroke paths only, in order)
"""
import json, re, sys, urllib.parse, urllib.request, xml.etree.ElementTree as ET
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

ja = chars_of("japanese")
(C / "strokes/japanese").mkdir(parents=True, exist_ok=True)
for c in ja:
    out = C / f"strokes/japanese/{ord(c):x}.svg"
    if out.exists() and "--force" not in sys.argv:
        continue
    root = ET.fromstring(get(f"https://raw.githubusercontent.com/KanjiVG/kanjivg/master/kanji/{ord(c):05x}.svg").decode())
    ds = [e.get("d") for e in root.iter("{http://www.w3.org/2000/svg}path") if e.get("d")]
    assert ds and all(re.fullmatch(r"[MmCcSsLlZzHhVvQqTtAa0-9.,\s-]+", d) for d in ds)
    paths = "".join(f'<path d="{d}"/>' for d in ds)
    out.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 109 109"><!-- KanjiVG (c) Ulrich Apel, CC BY-SA 3.0 -->'
                   '<g fill="none" stroke="#000" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
                   f"{paths}</g></svg>")
    print("ja", c, len(ds), "strokes")
prune("japanese", {f"{ord(c):x}" for c in ja})
