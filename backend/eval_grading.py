"""Calibrate the measured grader. Synthetic "handwriting" on real notebook paper (teammate photos):

  good   target rendered in 3 handwriting-like fonts per script, small elastic warp, ±6° rotation, noise
  messy  same fonts, strong warp, gaps in strokes, wobbly thickness, a part shifted out of place
  wrong  a different character of the same script
  blank  paper only (must be status no_writing)
  real   teammates' real handwritten capitals (test_data/handwriting/labels.json), graded as Latin

uv run python eval_grading.py            shape only (fast, no models)
uv run python eval_grading.py --live     full /grade path incl. qwen2.5vl rubric (writes test_data/grading_eval.md)
"""

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

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
TEST_DATA = HERE / "test_data"

A = "/System/Library/AssetsV2/PreinstalledAssetsV2/InstallWithOs/com_apple_MobileAsset_Font7/"
FONTS = {
    "mandarin": [(A + "dad866cc4d34849677c7073ad9899f251bfcc1de.asset/AssetData/Hanzipen.ttc", 0),
                 (A + "c8c242f5f5783386130f8a30fdf729841c9643e7.asset/AssetData/Hannotate.ttc", 0),
                 (A + "5d1d57301e8ef3e3e0319d4e9360da73857617b6.asset/AssetData/WawaSC-Regular.otf", 0)],
    "hindi": [(A + "fc316c050329113236e0b24839a003a9e6a6bbd3.asset/AssetData/Baloo-Devanagari.ttc", 0),
              (A + "091248da8cd15aed5188039d58196e00f64d8253.asset/AssetData/Mukta-Devanagari.ttc", 0),
              (A + "d045a5772de0bc474a9b792cb2cb5caf9951a03d.asset/AssetData/TiroHindi.ttc", 1)],
    "arabic": [("/System/Library/Fonts/Supplemental/DecoTypeNaskh.ttc", 0),
               ("/System/Library/Fonts/Supplemental/Farah.ttc", 0),
               ("/System/Library/Fonts/Supplemental/Diwan Kufi.ttc", 0)],
    "russian": [("/System/Library/Fonts/Supplemental/Comic Sans MS.ttf", 0),
                (A + "b41566ffe4ed54c94a9f6eb50514a24532ec0127.asset/AssetData/Klee.ttc", 1),
                (A + "dad866cc4d34849677c7073ad9899f251bfcc1de.asset/AssetData/Hanzipen.ttc", 0)],
    "hebrew": [("/System/Library/Fonts/Supplemental/Raanana.ttc", 0),
               ("/System/Library/Fonts/Supplemental/Corsiva.ttc", 0),
               ("/System/Library/Fonts/ArialHB.ttc", 0)],
    "greek": [("/System/Library/Fonts/Supplemental/Comic Sans MS.ttf", 0),
              (A + "11a76f9d5fd800227415e64d90ddc450c8acac3e.asset/AssetData/Kaiti.ttc", 0),
              ("/System/Library/Fonts/Avenir Next.ttc", 4)],
}
TARGETS = {  # target: a wrong character from the same lesson set
    "mandarin": [("水", "你"), ("你", "好"), ("好", "水"), ("友", "朋")],
    "hindi": [("न", "म"), ("म", "क"), ("क", "द")],
    "arabic": [("م", "ر"), ("ب", "ش"), ("ر", "ب")],
    "russian": [("п", "в"), ("д", "т"), ("в", "и")],
    "hebrew": [("ש", "ל"), ("ל", "ת"), ("ת", "ש")],
    "greek": [("λ", "γ"), ("ν", "ε"), ("ε", "λ")],
}


def paper(writer: int) -> Image.Image:
    im = ImageOps.exif_transpose(Image.open(TEST_DATA / "handwriting" / f"writer{writer}.jpg")).convert("RGB")
    w, h = im.size
    box = (int(0.30 * w), int(0.45 * h), int(0.30 * w) + int(0.55 * w), int(0.45 * h) + int(0.55 * w * 0.75))
    return im.crop(box).resize((640, 480))


def elastic(mask: np.ndarray, alpha: float, sigma: float, rng) -> np.ndarray:
    h, w = mask.shape
    dx = cv2.GaussianBlur((rng.random((h, w)) * 2 - 1).astype(np.float32), (0, 0), sigma) * alpha
    dy = cv2.GaussianBlur((rng.random((h, w)) * 2 - 1).astype(np.float32), (0, 0), sigma) * alpha
    x, y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(mask, x + dx, y + dy, cv2.INTER_LINEAR)


def render(char: str, font: tuple, kind: str, writer: int, rng) -> bytes:
    f = ImageFont.truetype(font[0], 240, index=font[1])
    layer = Image.new("L", (640, 480), 0)
    ImageDraw.Draw(layer).text((320, 240), char, font=f, fill=255, anchor="mm")
    m = np.array(layer)
    ys, xs = np.nonzero(m)
    if not len(xs):
        raise ValueError(f"{font[0]} can't render {char}")
    if kind in ("good", "wrong"):
        m = elastic(m, 18, 14, rng)
    else:  # messy
        m = elastic(m, 55, 11, rng)
        # gaps: erase a few small blobs on the strokes
        on = np.argwhere(m > 128)
        for _ in range(3):
            y, x = on[rng.integers(len(on))]
            cv2.circle(m, (int(x), int(y)), int(rng.integers(7, 12)), 0, -1)
        # wobbly thickness
        k = int(rng.integers(3, 7))
        m = cv2.dilate(m, np.ones((k, k), np.uint8)) if rng.random() < 0.5 else cv2.erode(m, np.ones((3, 3), np.uint8))
        # one part shifted out of place
        x0, x1 = xs.min(), xs.max()
        cut = int(x0 + (x1 - x0) * rng.uniform(0.55, 0.7))
        part = m[:, cut:].copy()
        m[:, cut:] = 0
        dy, dx = int(rng.integers(12, 26)) * (1 if rng.random() < 0.5 else -1), int(rng.integers(6, 16))
        shifted = np.roll(np.roll(part, dy, 0), dx, 1)
        m[:, cut:] = np.maximum(m[:, cut:], shifted[:, : 640 - cut])
    ang = float(rng.uniform(-6, 6))
    M = cv2.getRotationMatrix2D((320, 240), ang, 1.0)
    m = cv2.warpAffine(m, M, (640, 480))
    pap = paper(writer)
    ink = Image.new("RGB", pap.size, (28, 30, 48))
    pap.paste(ink, mask=Image.fromarray(m))
    a = np.asarray(pap).astype(np.float32)
    a += rng.normal(0, 4, a.shape)
    g = np.linspace(1 - rng.uniform(0, 0.25), 1, 640, dtype=np.float32)[None, :, None]  # shadow
    out = io.BytesIO()
    Image.fromarray((a * g).clip(0, 255).astype(np.uint8)).save(out, "JPEG", quality=85)
    return out.getvalue()


def blank(writer: int) -> bytes:
    out = io.BytesIO()
    paper(writer).save(out, "JPEG", quality=85)
    return out.getvalue()


def real_crops() -> list[tuple[str, bytes]]:
    lab = json.loads((TEST_DATA / "handwriting" / "labels.json").read_text())
    out = []
    for c in lab["crops"]:
        im = ImageOps.exif_transpose(Image.open(TEST_DATA / "handwriting" / f"writer{c['writer']}.jpg")).convert("RGB")
        w, h = im.size
        x0, y0, x1, y1 = c["box"]
        # the pair box holds two letters; the target is the left one
        crop = im.crop((int(x0 * w), int(y0 * h), int((x0 + (x1 - x0) * 0.55) * w), int(y1 * h)))
        crop = ImageOps.expand(crop.resize((crop.width * 4, crop.height * 4)), border=40, fill=crop.getpixel((2, 2)))
        b = io.BytesIO()
        crop.save(b, "JPEG", quality=90)
        out.append((c["target"], b.getvalue()))
    return out


def samples(seed: int = 7) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for lang, pairs in TARGETS.items():
        for tgt, wrong in pairs:
            for fi, font in enumerate(FONTS[lang]):
                out.append({"lang": lang, "char": tgt, "kind": "good", "font": fi,
                            "jpeg": render(tgt, font, "good", 1 + fi % 3, rng)})
            fi = int(rng.integers(3))
            out.append({"lang": lang, "char": tgt, "kind": "messy", "font": fi,
                        "jpeg": render(tgt, FONTS[lang][fi], "messy", 1 + fi % 3, rng)})
            out.append({"lang": lang, "char": tgt, "kind": "wrong", "font": 0, "written": wrong,
                        "jpeg": render(wrong, FONTS[lang][0], "good", 2, rng)})
    for w in (1, 2, 3):
        out.append({"lang": "greek", "char": "λ", "kind": "blank", "jpeg": blank(w)})
    for tgt, jpg in real_crops():
        out.append({"lang": "latin", "char": tgt, "kind": "real", "jpeg": jpg})
    return out


def run_shape(items: list[dict]) -> list[dict]:
    from worn import measure
    rows = []
    for it in items:
        t = time.perf_counter()
        fw = measure.find_writing(it["jpeg"])
        if fw is None:
            rows.append({**{k: v for k, v in it.items() if k != "jpeg"}, "status": "no_writing", "shape": None,
                         "ms": round((time.perf_counter() - t) * 1000)})
            continue
        sh = measure.shape(fw["mask"], it["lang"], it["char"])
        rows.append({**{k: v for k, v in it.items() if k != "jpeg"}, "status": "ok", "shape": sh["score"],
                     "raw": sh["raw"], "other": sh.get("best_other"), "other_char": sh.get("other_char"),
                     "metrics": sh["metrics"], "ms": round((time.perf_counter() - t) * 1000)})
    return rows


async def run_full(items: list[dict]) -> list[dict]:
    from worn import grading
    rows = []
    for it in items:
        t = time.perf_counter()
        r = await grading.grade(it["jpeg"], it["char"], it["lang"])
        rows.append({**{k: v for k, v in it.items() if k != "jpeg"}, "status": r["status"], "score": r["score"],
                     "shape": (r.get("shape") or {}).get("score"), "rubric": (r.get("rubric") or {}).get("score"),
                     "seen": (r.get("rubric") or {}).get("seen"), "correct": r["correct"],
                     "ms": round((time.perf_counter() - t) * 1000)})
        print(f"{it['kind']:6} {it['lang']:8} {it['char']} → {r['status']} {r['score']} "
              f"(shape {rows[-1]['shape']}, rubric {rows[-1]['rubric']}, seen {rows[-1]['seen']!r}) {rows[-1]['ms']} ms",
              flush=True)
    return rows


def summarize(rows: list[dict], key: str) -> dict:
    out = {}
    for kind in ("good", "messy", "wrong", "blank", "real"):
        rs = [r for r in rows if r["kind"] == kind]
        if not rs:
            continue
        vals = [r[key] for r in rs if r.get(key) is not None]
        out[kind] = {"n": len(rs), "no_writing": sum(1 for r in rs if r["status"] == "no_writing"),
                     "mean": round(statistics.mean(vals), 1) if vals else None,
                     "min": min(vals) if vals else None, "max": max(vals) if vals else None,
                     "p10": round(float(np.percentile(vals, 10)), 1) if vals else None,
                     "p90": round(float(np.percentile(vals, 90)), 1) if vals else None,
                     "correct": sum(1 for r in rs if r.get("correct")) if "correct" in rs[0] else None}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    a = ap.parse_args()
    items = samples()
    if not a.live:
        rows = run_shape(items)
        for r in rows:
            if r["kind"] != "good" or (r["shape"] or 0) < 70:
                print(r["kind"], r["lang"], r["char"], r.get("written", ""), r["status"], r["shape"], r.get("raw"),
                      r.get("other"), r.get("other_char"), r.get("metrics"))
        print(json.dumps(summarize(rows, "shape"), ensure_ascii=False, indent=1))
        print("avg ms", round(statistics.mean(r["ms"] for r in rows)))
    else:
        rows = asyncio.run(run_full(items))
        s = summarize(rows, "score")
        print(json.dumps(s, ensure_ascii=False, indent=1))
        (TEST_DATA / "grading_eval.json").write_text(json.dumps({"summary": s, "rows": rows}, ensure_ascii=False, indent=1))
