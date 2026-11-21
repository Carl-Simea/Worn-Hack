"""Checks every lesson item, offline (no backend needed):
   python3 content/tools/verify_items.py            # prints a per-language checklist, exit 1 on any problem
   python3 content/tools/verify_items.py --md       # the same checklist as Markdown (pasted into REMAINING-C.md)

Per item: native text, chars[] (joined = text without spaces), romanization, meaning, per-char romanization,
audio file that decodes (afinfo/afconvert, >= 0.4 s), and a stroke file for every char.
Per stroke file (SVG, all scripts but Mandarin; Mandarin = hanzi-writer JSON):
  - parses, has >= 1 <path>, paths are the strokes in order (document order = stroke order, no ids out of order)
  - every coordinate inside the 100x100 writing box (viewBox 0 0 109 109, box = 4.5..104.5, 1-unit tolerance)
  - direction: RTL joined words (Arabic/Hebrew multi-letter files) go right to left: the first stroke's
    centre is right of the last stroke's centre; LTR multi-glyph files (Hindi conjuncts) go left to right
    (the headline, drawn last, is ignored).
"""
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

C = Path(__file__).resolve().parent.parent
LANGS = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]
LO, HI, TOL = 4.5, 104.5, 1.0
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def audio_seconds(p):
    try:
        out = subprocess.run(["afinfo", str(p)], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"estimated duration: ([\d.]+)", out)
        if not m:
            return 0.0
        # decode it fully, so a truncated file fails here
        with tempfile.TemporaryDirectory() as td:
            out_wav = Path(td) / "a.wav"
            r = subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(p), str(out_wav)],
                               capture_output=True, timeout=20)
            ok = r.returncode == 0 and out_wav.stat().st_size > 8000
        return float(m.group(1)) if ok else 0.0
    except Exception:
        return 0.0


def path_points(d):
    """Absolute M/C/L/Q commands only (what strokes_authored.py writes): every number pair is a point."""
    if re.search(r"[a-z]", re.sub(r"e-?\d", "", d)):
        return None   # relative commands: not ours, flag it
    nums = [float(x) for x in NUM.findall(d)]
    return list(zip(nums[0::2], nums[1::2]))


def check_svg(p, rtl, multi):
    probs = []
    try:
        root = ET.parse(p).getroot()
    except Exception as e:
        return [f"{p.name}: does not parse ({e})"], 0
    if root.get("viewBox") != "0 0 109 109":
        probs.append(f"{p.name}: viewBox {root.get('viewBox')}")
    paths = [el for el in root.iter() if el.tag.endswith("path")]
    if not paths:
        return probs + [f"{p.name}: no strokes"], 0
    ids = [el.get("id") for el in paths if el.get("id")]
    nums = [int(m.group(1)) for i in ids if (m := re.search(r"(\d+)$", i))]
    if nums and nums != sorted(nums):
        probs.append(f"{p.name}: stroke ids out of order {nums}")
    centres = []
    for k, el in enumerate(paths, 1):
        pts = path_points(el.get("d", ""))
        if pts is None:
            probs.append(f"{p.name}: stroke {k} uses relative commands")
            continue
        out = [(x, y) for x, y in pts if not (LO - TOL <= x <= HI + TOL and LO - TOL <= y <= HI + TOL)]
        if out:
            probs.append(f"{p.name}: stroke {k} leaves the box at {out[0]}")
        xs = [x for x, _ in pts]
        centres.append((min(xs) + max(xs)) / 2)
    if multi and len(centres) >= 2:
        body = centres[:-1] if not rtl else centres   # Hindi: the last stroke is the headline
        if rtl and not body[0] > body[-1]:
            probs.append(f"{p.name}: joined word does not run right to left ({body[0]:.0f} → {body[-1]:.0f})")
        if not rtl and len(body) >= 2 and not body[0] <= body[-1] + 8:
            probs.append(f"{p.name}: does not run left to right ({body[0]:.0f} → {body[-1]:.0f})")
    return probs, len(paths)


def check_hanzi(p):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        n = len(d.get("strokes") or [])
        ok = n and len(d.get("medians") or []) == n
        return ([] if ok else [f"{p.name}: strokes/medians mismatch"]), n
    except Exception as e:
        return [f"{p.name}: {e}"], 0


def stroke_file(lang, ch):
    stem = "-".join(f"{ord(c):x}" for c in ch)
    for ext in ("svg", "json"):
        f = C / "strokes" / lang / f"{stem}.{ext}"
        if f.exists():
            return f
    return None


def main():
    md = "--md" in sys.argv
    total = 0
    lines = []
    for lang in LANGS:
        L = json.loads((C / f"{lang}.json").read_text(encoding="utf-8"))
        rtl = bool(L.get("rtl"))
        lines.append(f"\n### {L['name']}{' (right to left)' if rtl else ''}\n" if md else f"\n{L['name']}")
        if md:
            lines.append("| Item | Text | Chars | Rom. | Meaning | Audio | Strokes (files · strokes) | Result |")
            lines.append("|---|---|---|---|---|---|---|---|")
        for it in L["phrases"]:
            probs = []
            text, chars = it.get("text", ""), it.get("chars") or []
            if not text:
                probs.append("no text")
            if not chars:
                probs.append("no chars")
            letters = [c for c in chars if not (len(chars) > 1 and c == text.replace(" ", ""))]
            if "".join(letters) != text.replace(" ", ""):
                probs.append(f"chars {''.join(letters)!r} != text")
            for k in ("romanization", "meaning"):
                if not it.get(k):
                    probs.append(f"no {k}")
            if len(it.get("char_romanization") or []) != len(chars):
                probs.append("char_romanization length")
            secs = audio_seconds(C / it.get("audio", "-")) if it.get("audio") else 0.0
            if secs < 0.4:
                probs.append(f"audio {it.get('audio')} missing or doesn't decode")
            nfiles = nstrokes = 0
            for ch in chars:
                f = stroke_file(lang, ch)
                if not f:
                    probs.append(f"no stroke file for {ch}")
                    continue
                if f.suffix == ".json":
                    pr, n = check_hanzi(f)
                else:
                    pr, n = check_svg(f, rtl, multi=len(ch) > 1)
                probs += pr
                nfiles += 1
                nstrokes += n
            total += len(probs)
            ok = "✅" if not probs else "❌ " + "; ".join(probs)
            if md:
                y = lambda b: "✓" if b else "✗"
                lines.append(f"| {it['id']} | {text} | {y(chars)} {len(chars)} | {y(it.get('romanization'))} "
                             f"{it.get('romanization','')} | {y(it.get('meaning'))} | {y(secs >= 0.4)} {secs:.1f} s | "
                             f"{nfiles}/{len(chars)} · {nstrokes} | {ok} |")
            else:
                lines.append(f"  {it['id']:<10} {text:<12} chars {len(chars)}  audio {secs:.1f}s  strokes "
                             f"{nfiles}/{len(chars)} files, {nstrokes} paths  {ok}")
    print("\n".join(lines))
    print(f"\n{total} problems" + (" across 30 items" if not md else ""))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
