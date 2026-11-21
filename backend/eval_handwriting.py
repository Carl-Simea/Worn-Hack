"""Real-world evaluation of the three perception tiers on teammates' handwriting photos.

    uv run python eval_handwriting.py            # tiers 1 + 2 (no models needed)
    uv run python eval_handwriting.py --live     # + tier 3 with qwen2.5vl:7b (Ollama running)

Inputs: test_data/handwriting/writer{1,2,3}.jpg (pen on lined notebook paper, real light, 3 writers)
and labels.json (hand-labeled letter pairs). Writes test_data/eval_results.{json,md}."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
DATA = HERE / "test_data"
HW = DATA / "handwriting"
FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
sys.path.insert(0, str(HERE))

# One target per language plus a confusable "wrong" char from the same script.
PAIRS = [("mandarin", "你", "好"), ("mandarin", "水", "永"), ("hindi", "न", "म"), ("arabic", "م", "ر"),
         ("russian", "П", "Л"), ("hebrew", "ש", "ת"), ("greek", "λ", "ν")]
STYLES = {
    "print": dict(),
    "cursive-ish": dict(slant=0.28),
    "marker": dict(stroke=4),
    "mixed": dict(slant=-0.18, tilt=7, shadow=0.35),
}
HARSH = ("bad", "wrong", "ugly", "messy", "sloppy", "poor", "terrible", "awful", "careless", "stupid")


# ------------------------------------------------------------------ image helpers

def load(writer: int) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(HW / f"writer{writer}.jpg")).convert("RGB")


def paper_crop(writer: int = 1) -> Image.Image:
    """A blank patch of the teammate's real page (ruled lines, real light), 640x480."""
    im = load(writer)
    w, h = im.size
    box = (int(0.30 * w), int(0.45 * h), int(0.30 * w) + int(0.55 * w), int(0.45 * h) + int(0.55 * w * 0.75))
    return im.crop(box).resize((640, 480))


def jpeg(img: Image.Image, q: int = 88) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=q)
    return out.getvalue()


def degrade(img: Image.Image, tilt: float = 0.0, shadow: float = 0.0) -> Image.Image:
    if tilt:
        img = img.rotate(tilt, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(120, 110, 100))
    if shadow:
        a = np.asarray(img).astype("float32")
        g = np.linspace(1 - shadow, 1, a.shape[1], dtype="float32")[None, :, None]
        img = Image.fromarray((a * g).clip(0, 255).astype("uint8"))
    return img


def write_on_paper(char: str, writer: int = 1, *, size: int = 230, slant: float = 0.0, stroke: int = 0,
                   tilt: float = 0.0, shadow: float = 0.0, ink=(28, 30, 48)) -> bytes:
    """char as pen ink on a real notebook page, with optional slant / marker weight / tilt / shadow."""
    paper = paper_crop(writer)
    layer = Image.new("L", paper.size, 0)
    ImageDraw.Draw(layer).text((320, 235), char, font=ImageFont.truetype(FONT, size), fill=255, anchor="mm",
                               stroke_width=stroke, stroke_fill=255)
    if slant:
        layer = layer.transform(layer.size, Image.Transform.AFFINE, (1, slant, -slant * 240, 0, 1, 0),
                                resample=Image.Resampling.BICUBIC)
    paper.paste(Image.new("RGB", paper.size, ink), mask=layer)
    return jpeg(degrade(paper, tilt, shadow))


def labeled_crops() -> list[dict]:
    out = []
    for c in json.loads((HW / "labels.json").read_text())["crops"]:
        im = load(c["writer"])
        w, h = im.size
        b = c["box"]
        crop = im.crop((int(b[0] * w), int(b[1] * h), int(b[2] * w), int(b[3] * h)))
        # pad onto the same page's paper so it looks like a close-up glasses photo, then upscale
        scale = 420 / max(crop.size)
        crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.Resampling.LANCZOS)
        canvas = paper_crop(c["writer"])
        canvas.paste(crop, ((640 - crop.width) // 2, (480 - crop.height) // 2))
        out.append({**c, "image": canvas})
    return out


def _ms(vals):
    return {"avg_ms": round(statistics.mean(vals), 1), "max_ms": round(max(vals), 1)} if vals else {}


# ------------------------------------------------------------------ tier 1

def tier1() -> dict:
    from worn import inkdiff, strokes

    def move(im, dx, dy, deg):
        h, w = im.shape[:2]
        m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1)
        m[:, 2] += [dx, dy]
        return cv2.warpAffine(im, m, (w, h), borderMode=cv2.BORDER_REPLICATE)

    def shade(im, k):
        g = np.tile(np.linspace(k, 1, im.shape[1], dtype=np.float32), (im.shape[0], 1))[..., None]
        return np.clip(im * g, 0, 255).astype(np.uint8)

    def add_stroke(im):
        im = im.copy()
        h, w = im.shape[:2]
        cv2.line(im, (int(.45 * w), int(.40 * h)), (int(.58 * w), int(.43 * h)), (40, 35, 45), 3, cv2.LINE_AA)
        return im

    enc = lambda im, q=90: cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()
    rows, lat = [], []
    for wi in (1, 2, 3):
        base = strokes.decode((HW / f"writer{wi}.jpg").read_bytes())
        cases = {
            "camera shift 7px + 1.5°": (move(base, 7, -5, 1.5), False),
            "20% dimmer": ((base * 0.8).astype(np.uint8), False),
            "shadow sweep 45%": (shade(base, 0.55), False),
            "JPEG recompress q60": (cv2.imdecode(np.frombuffer(enc(base, 60), np.uint8), 1), False),
            "shift + shadow": (shade(move(base, -6, 4, -1.2), 0.7), False),
            "real new stroke (moved camera)": (add_stroke(move(base, 4, 3, 0.8)), True),
        }
        for name, (im, expect) in cases.items():
            r = inkdiff.diff(enc(base), enc(im))
            lat.append(r["ms"])
            rows.append({"writer": wi, "case": name, "expected": expect, "got": r["new_stroke"],
                         "ok": r["new_stroke"] == expect, "new_ink_frac": r["new_ink_frac"], "ms": r["ms"]})
    false_pos = sum(1 for r in rows if not r["expected"] and r["got"])
    misses = sum(1 for r in rows if r["expected"] and not r["got"])
    return {"cases": rows, "accuracy": sum(r["ok"] for r in rows) / len(rows), "false_new_stroke": false_pos,
            "missed_strokes": misses, "n": len(rows), "latency": _ms(lat)}


# ------------------------------------------------------------------ ink extraction on the real pages

def ink_precision() -> dict:
    from worn import strokes
    out = []
    for wi in (1, 2, 3):
        m = strokes.extract_ink(strokes.decode((HW / f"writer{wi}.jpg").read_bytes()))
        h = m.shape[0]
        ys, _ = np.nonzero(m)
        band = float(((ys > 0.03 * h) & (ys < 0.17 * h)).mean()) if len(ys) else 0.0
        out.append({"writer": wi, "ink_px": int(len(ys)), "in_writing_band": round(band, 3)})
    return {"pages": out, "min_precision": min(p["in_writing_band"] for p in out)}


# ------------------------------------------------------------------ tier 2

def tier2() -> dict:
    from worn import strokes
    rows, lat = [], []
    for lang, right, wrong in PAIRS:
        n = strokes.stroke_count(lang, right)
        for style, kw in STYLES.items():
            for wi in (1, 2, 3):
                img_r = write_on_paper(right, wi, **kw)
                img_w = write_on_paper(wrong, wi, **kw)
                t = time.perf_counter()
                m = strokes.match_stroke(img_r, lang, right, n - 1)
                lat.append((time.perf_counter() - t) * 1000)
                s_r = strokes.compare_full(img_r, lang, right)["score"]
                s_w = strokes.compare_full(img_w, lang, right)["score"]
                rows.append({"lang": lang, "char": right, "style": style, "writer": wi, "final_stroke_done": m["done"],
                             "score_right": s_r, "score_wrong": s_w, "separates": s_r > s_w})
    by_style = {}
    for st in STYLES:
        rs = [r for r in rows if r["style"] == st]
        by_style[st] = {"done_rate": round(sum(r["final_stroke_done"] for r in rs) / len(rs), 3),
                        "separation": round(sum(r["separates"] for r in rs) / len(rs), 3)}
    return {"by_style": by_style, "done_rate": round(sum(r["final_stroke_done"] for r in rows) / len(rows), 3),
            "separation": round(sum(r["separates"] for r in rows) / len(rows), 3), "n": len(rows),
            "latency": _ms(lat), "rows": rows}


# ------------------------------------------------------------------ tier 3 (live model)

async def tier3() -> dict:
    from worn import vision, llm
    rows, lat = [], []

    async def g(img_bytes, char, lang, kind, expect, meta):
        jp = vision.prep_image(img_bytes)
        t = time.perf_counter()
        try:
            r, _ = await vision.grade(jp, char, lang)
        except Exception as e:
            r = {"correct": None, "score": 0, "seen": "", "feedback": f"ERROR {e}"}
        ms = (time.perf_counter() - t) * 1000
        lat.append(ms)
        harsh = [w for w in HARSH if w in r["feedback"].lower().replace(".", " ").split()]
        rows.append({"kind": kind, **meta, "target": char, "expected": expect, "correct": r["correct"],
                     "ok": r["correct"] == expect, "seen": r["seen"], "score": r["score"],
                     "feedback": r["feedback"], "harsh_words": harsh, "ms": round(ms)})

    # (a) real teammate handwriting (Latin letter pairs), as-is and tilted + shadowed
    for c in labeled_crops():
        meta = {"writer": c["writer"]}
        await g(jpeg(c["image"]), c["target"], "latin", "real: as photographed", True, meta)
        await g(jpeg(degrade(c["image"], 8, 0.45)), c["target"], "latin", "real: tilted 8° + shadow", True, meta)
        other = "Q" if c["target"] != "Q" else "Z"
        await g(jpeg(c["image"]), other, "latin", "real: wrong target (must reject)", False, meta)
    # (b) target scripts on real paper, tilted + shadowed, print and cursive-ish
    for lang, right, wrong in PAIRS:
        for style in ("print", "mixed"):
            kw = STYLES[style]
            await g(write_on_paper(right, 2, **kw), right, lang, f"script on real paper: {style}", True, {"lang": lang})
            await g(write_on_paper(wrong, 2, **kw), right, lang, f"script on real paper: {style}, wrong char",
                    False, {"lang": lang})
    kinds = {}
    for r in rows:
        k = kinds.setdefault(r["kind"], {"n": 0, "ok": 0})
        k["n"] += 1
        k["ok"] += r["ok"]
    for k in kinds.values():
        k["accuracy"] = round(k["ok"] / k["n"], 3)
    try:
        await llm.client().aclose()
    except Exception:
        pass
    return {"by_kind": kinds, "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3), "n": len(rows),
            "harsh_feedback": sum(1 for r in rows if r["harsh_words"]), "latency": _ms(lat), "rows": rows}


async def tier3_agent() -> dict:
    """The full /grade path (vision + template arbitration + echo/symbol guards + tutor), right and
    wrong letters on real paper. Uses whatever WORN_DATA_DIR is set (the CLI sets a temp one)."""
    from worn import agent, vision, llm
    rows = []
    for lang, right, wrong in PAIRS:
        for style in ("print", "mixed"):
            for kind, ch in (("right", right), ("wrong", wrong)):
                jp = vision.prep_image(write_on_paper(ch, 2, **STYLES[style]))
                t = time.perf_counter()
                g = await agent.run_grade(jp, right, lang, None, None)
                rows.append({"lang": lang, "target": right, "wrote": ch, "style": style, "kind": kind,
                             "correct": g["correct"], "ok": g["correct"] == (kind == "right"), "seen": g["seen"],
                             "template": g["template_score"], "feedback": g["feedback"], "reaction": g["reaction"],
                             "ms": round((time.perf_counter() - t) * 1000)})
    try:
        await llm.client().aclose()
    except Exception:
        pass
    acc = lambda k: round(sum(r["ok"] for r in rows if r["kind"] == k) / max(1, sum(r["kind"] == k for r in rows)), 3)
    return {"right_accepted": acc("right"), "wrong_rejected": acc("wrong"), "n": len(rows),
            "latency": _ms([r["ms"] for r in rows]), "rows": rows}


# ------------------------------------------------------------------ report

def report(res: dict) -> str:
    L = ["# Real-world perception eval (teammate notebook photos)", "",
         f"Run {time.strftime('%Y-%m-%d %H:%M')}. Inputs: `test_data/handwriting/writer{{1,2,3}}.jpg` + `labels.json`.", ""]
    ip = res["ink"]
    L += ["## Ink extraction on full notebook pages",
          "Share of detected ink inside the hand-written band (rest = lines, holes, spiral, shadow false positives): "
          + ", ".join(f"writer{p['writer']} {p['in_writing_band']:.0%}" for p in ip["pages"]), ""]
    t1 = res["tier1"]
    L += ["## Tier 1: ink diff (new stroke?)",
          f"Accuracy **{t1['accuracy']:.0%}** on {t1['n']} cases; false new-stroke {t1['false_new_stroke']}, "
          f"missed strokes {t1['missed_strokes']}; latency avg {t1['latency']['avg_ms']} ms, max {t1['latency']['max_ms']} ms.", "",
          "| case | writer 1 | writer 2 | writer 3 |", "|---|---|---|---|"]
    for case in dict.fromkeys(r["case"] for r in t1["cases"]):
        cells = [("✅" if r["ok"] else "❌") + f" {r['new_ink_frac']:.5f}" for r in t1["cases"] if r["case"] == case]
        L.append(f"| {case} | " + " | ".join(cells) + " |")
    t2 = res["tier2"]
    L += ["", "## Tier 2: stroke match across handwriting styles",
          f"{t2['n']} renders ({len(PAIRS)} chars x 4 styles x 3 real papers). Final stroke accepted **{t2['done_rate']:.0%}**, "
          f"right char scores above confusable char **{t2['separation']:.0%}**; latency avg {t2['latency']['avg_ms']} ms, "
          f"max {t2['latency']['max_ms']} ms (budget 300).", "", "| style | final stroke done | right > wrong |", "|---|---|---|"]
    for st, v in t2["by_style"].items():
        L.append(f"| {st} | {v['done_rate']:.0%} | {v['separation']:.0%} |")
    if "tier3" in res:
        t3 = res["tier3"]
        L += ["", "## Tier 3: qwen2.5vl:7b grading",
              f"Overall **{t3['accuracy']:.0%}** on {t3['n']} grades; harsh feedback {t3['harsh_feedback']}; "
              f"latency avg {t3['latency']['avg_ms']:.0f} ms, max {t3['latency']['max_ms']:.0f} ms.", "",
              "| case | accuracy | n |", "|---|---|---|"]
        for k, v in t3["by_kind"].items():
            L.append(f"| {k} | {v['accuracy']:.0%} | {v['n']} |")
        if "tier3_agent" in res:
            ta = res["tier3_agent"]
            L += ["", "## Tier 3 + tutor agent (the full /grade)",
                  f"Right letters accepted **{ta['right_accepted']:.0%}**, wrong letters rejected **{ta['wrong_rejected']:.0%}** "
                  f"({ta['n']} grades, {len(PAIRS)} targets x print/slanted+tilted+shadowed on real paper); "
                  f"latency avg {ta['latency']['avg_ms']:.0f} ms, max {ta['latency']['max_ms']:.0f} ms (includes the tutor LLM)."]
            L += [f"- miss: target {r['target']} wrote {r['wrote']} ({r['style']}): correct={r['correct']} seen {r['seen']!r}"
                  for r in ta["rows"] if not r["ok"]]
        bad = [r for r in t3["rows"] if not r["ok"]]
        if bad:
            L += ["", "Misses:"] + [f"- {r['kind']}: target {r['target']} read {r['seen']!r} ({r['score']}): "
                                    f"\"{r['feedback']}\"" for r in bad[:12]]
    return "\n".join(L) + "\n"


def run(live: bool) -> dict:
    res = {"ink": ink_precision(), "tier1": tier1(), "tier2": tier2()}
    if live:
        res["tier3"] = asyncio.run(tier3())
        res["tier3_agent"] = asyncio.run(tier3_agent())
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="include tier 3 (needs Ollama + qwen2.5vl:7b)")
    a = ap.parse_args()
    import os
    import tempfile
    os.environ.setdefault("WORN_DATA_DIR", tempfile.mkdtemp(prefix="worn-eval-"))  # never touch the real journal
    os.environ.setdefault("WORN_CAPTURE_DIR", tempfile.mkdtemp(prefix="worn-eval-cap-"))
    res = run(a.live)
    md = report(res)
    (DATA / "eval_results.md").write_text(md, encoding="utf-8")
    (DATA / "eval_results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(md)
