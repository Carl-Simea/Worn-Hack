"""Writes content/REVIEW.md from the lesson files (+ names/ examples) so native speakers can check every item.
   python3 content/tools/make_review.py
"""
import json
from pathlib import Path

C = Path(__file__).resolve().parent.parent
LANGS = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]

out = ["# Worn content review", "",
       "Please check every row with a native speaker at the venue. Tick the box if it's right; otherwise write the fix",
       "in the Notes column (or tell agent C). **If anything is wrong and there's no time to fix it, we cut that item.**", "",
       "Things to check: the native text, the romanization, the meaning, the one-line notes, and the audio",
       "(`content/audio/{lang}/{id}.m4a`, macOS text-to-speech). For Hindi, Arabic, Russian, Hebrew and Greek, also check the",
       "**suggested** stroke order in `content/review/strokes_{lang}.png` (Mandarin uses standard data).", "",
       "**Stroke shapes also affect grading:** the backend compares handwriting against these templates to settle",
       "look-alike misreads (ש vs ע, ر vs ن). A letter whose template doesn't look like normal handwriting can get",
       "correct writing rejected (the old Greek γ was Y-shaped). Flag any letter whose shape looks off, not only its order.", ""]
for lang in LANGS:
    L = json.loads((C / f"{lang}.json").read_text(encoding="utf-8"))
    out += [f"## {L['name']} · {L['script']} ({L['script_type']}{', right to left' if L['rtl'] else ''})", "",
            f"_{L['about']}_  Stroke order: **{L['stroke_order']}** ({L['stroke_source']}).", "",
            "| ✓ | Native | Romanization | Meaning | Written as (one per photo) | How the script works | Dictation hint | Notes |",
            "|---|---|---|---|---|---|---|---|"]
    for p in L["phrases"]:
        chars = " · ".join(p["chars"])
        out.append(f"| ☐ | **{p['text']}** | {p['romanization']} | {p['meaning']} | {chars} | {p['how']} | {p['dictation']} | |")
    out.append("")

names = C / "names"
if names.is_dir():
    out += ["## Write your name (approximate sound maps)", "",
            "These are rough English-sound → script maps for fun, not official transliterations. Check the examples.", ""]
    for f in sorted(names.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if "script" not in d:  # examples.json is a cross-script lookup table, not a script map
            continue
        out += [f"### {d['script']} ({f.name})", "", "| ✓ | English name | Written | Notes |", "|---|---|---|---|"]
        for ex in d.get("examples", []):
            out.append(f"| ☐ | {ex['name']} | **{ex['written']}** | {ex.get('note', '')} |")
        out.append("")

pb = C / "phrases" / "examples.json"
if pb.exists():
    P = json.loads(pb.read_text(encoding="utf-8"))["phrases"]
    out += ["## Phrasebook for 'Help me write' (`phrases/examples.json`)", "",
            "Answered before any model, so a wrong row would be taught as-is. Check native text, romanization and notes.", "",
            "| ✓ | English | Language | Native | Romanization | Note |", "|---|---|---|---|---|---|"]
    for en, row in P.items():
        for lang, v in row.items():
            out.append(f"| ☐ | {en} | {lang} | **{v['native']}** | {v['romanization']} | {v.get('note', '')} |")
    out.append("")

for fname, title in (("reactions.json", "Reactions (spoken + shown)"), ("milestones.json", "Milestones")):
    f = C / fname
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        out += [f"## {title} (English only; check tone: goofy, never mean)", ""]
        for k, v in d.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and "lines" in v:
                out.append(f"- **{k}**: " + " / ".join(v["lines"]))
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, dict) and "lines" in vv:
                        out.append(f"- **{k} · {kk}**: " + " / ".join(vv["lines"]))
                    elif isinstance(vv, dict) and "spoken" in vv:
                        out.append(f"- **{k} · {kk}**: “{vv['spoken']}” (shown: {vv['shown']})")
        out.append("")

(C / "REVIEW.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("wrote content/REVIEW.md")
