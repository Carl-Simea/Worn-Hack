"""Measured grading: find the writing, compare its shape to the reference with several metrics, and
build the side-by-side image Scribi's rubric (qwen2.5vl) looks at.

  find_writing  paper skew from the ruled lines → deskew; lighting-normalized ink (strokes.extract_ink:
                shadows, ruled lines, holes, spiral removed); the main cluster of ink; tight crop + padding.
                No ink → None (status "no_writing", never a 0 score).
  shape         ink skeleton vs. reference skeletons (font glyph and stroke template) on a 128 px canvas,
                best over small rotations/slants: IoU of dilated masks, chamfer + Hausdorff-95 distance,
                3×3 ink-distribution grid, aspect ratio, component count, coverage (completeness) and
                precision (stray ink). The same score against the other characters of the script tells us
                whether the target is really the best explanation (wrong characters score low).
"""

from __future__ import annotations

import functools
import io
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import content, strokes

S = 128
FIT = 0.8
FONT_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "fonts"
REF_FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"  # last resort: covers every script
NOTO = {"mandarin": "NotoSansSC-Regular.ttf", "hindi": "NotoSansDevanagari-Regular.ttf",
        "arabic": "NotoNaskhArabic-Regular.ttf", "russian": "NotoSans-Regular.ttf",
        "hebrew": "NotoSansHebrew-Regular.ttf", "greek": "NotoSans-Regular.ttf", "latin": "NotoSans-Regular.ttf"}
POSES = [(a, sh) for a in (-8, 0, 8) for sh in (-0.25, 0.0, 0.25)]
FEW_POSES = [(0, 0.0), (-8, 0.0), (8, 0.0), (0, 0.25), (0, -0.25)]

# metric weights for the raw shape score (calibrated in eval_grading.py, see REMAINING-A.md)
W = {"iou": 0.20, "chamfer": 0.30, "hausdorff": 0.10, "grid": 0.20, "aspect": 0.10, "components": 0.10}
# shape score = raw mapped with these, minus a penalty when another character explains the ink better
RAW_LO, RAW_HI = 0.30, 0.78
# dense scripts (hanzi) and cursive-shaped ones (Arabic) reach lower raw similarity for the same quality
RAW_HI_LANG = {"mandarin": 0.70, "arabic": 0.66}
MARGIN_PENALTY = 4.0


# ------------------------------------------------------------------ 1. find the writing

def _skew_angle(bgr: np.ndarray) -> float:
    """Paper tilt in degrees from the ruled lines (0 if there are none)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    bg = strokes.paper_background(gray).astype(np.float32)
    faint = ((gray.astype(np.float32) / np.maximum(bg, 1)) < 0.9).astype(np.uint8) * 255
    lines = cv2.HoughLinesP(faint, 1, np.pi / 360, threshold=max(60, w // 6), minLineLength=int(0.3 * w),
                            maxLineGap=12)
    if lines is None:
        return 0.0
    ang = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) < 15:
            ang.append(a)
    return float(np.median(ang)) if len(ang) >= 3 else 0.0


def find_writing(raw: bytes | np.ndarray) -> dict | None:
    t0 = time.perf_counter()
    bgr = strokes.decode(raw) if isinstance(raw, (bytes, bytearray)) else raw
    angle = _skew_angle(bgr)
    if abs(angle) > 0.7:
        h, w = bgr.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        bgr = cv2.warpAffine(bgr, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    mask = strokes.extract_ink(bgr)
    h, w = mask.shape
    min_px = max(40, int(0.00012 * h * w))
    if int((mask > 0).sum()) < min_px:
        return None
    # the main cluster: strokes of one character sit close together; far specks and other words drop out
    # Characters have separate parts (亻 + 尔, Arabic dots, Devanagari matras), so pieces within ~10% of the
    # frame merge; then nearby clusters with a real share of ink join too.
    k = max(15, int(0.10 * min(h, w)))
    grown = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, lab = cv2.connectedComponents(grown, connectivity=8)
    if n <= 1:
        return None
    counts = np.bincount(lab[mask > 0].ravel(), minlength=n)
    counts[0] = 0
    best = int(counts.argmax())
    keep = lab == best
    ys0, xs0 = np.nonzero(keep)
    bx0, bx1, by0, by1 = xs0.min(), xs0.max(), ys0.min(), ys0.max()
    size = max(bx1 - bx0, by1 - by0)
    for i in range(1, n):
        if i == best or counts[i] < 0.08 * counts[best]:
            continue
        yi, xi = np.nonzero(lab == i)
        gap = max(0, max(bx0 - xi.max(), xi.min() - bx1, by0 - yi.max(), yi.min() - by1))
        if gap < 0.6 * size:
            keep |= lab == i
    ink = np.where(keep, mask, 0).astype(np.uint8)
    if int((ink > 0).sum()) < min_px:
        return None
    ys, xs = np.nonzero(ink)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    pad = max(8, int(0.15 * max(x1 - x0, y1 - y0)))
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad + 1), min(h, y1 + pad + 1)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    bg = strokes.paper_background(gray).astype(np.float32)
    flat = np.clip(gray.astype(np.float32) / np.maximum(bg, 1) * 255, 0, 255).astype(np.uint8)  # shadows gone
    crop_flat = flat[Y0:Y1, X0:X1]
    crop_flat = cv2.normalize(crop_flat, None, 0, 255, cv2.NORM_MINMAX)
    return {"mask": ink[Y0:Y1, X0:X1], "gray": crop_flat, "box": [int(X0), int(Y0), int(X1 - X0), int(Y1 - Y0)],
            "frame": [w, h], "angle": round(angle, 1), "ink_px": int((ink > 0).sum()),
            "ms": round((time.perf_counter() - t0) * 1000)}


# ------------------------------------------------------------------ 2. references

@functools.lru_cache(maxsize=64)
def _font(lang: str = "", size: int = 220):
    f = FONT_DIR / NOTO.get(lang, "")
    try:
        return ImageFont.truetype(str(f) if f.is_file() else REF_FONT, size)
    except OSError:
        return ImageFont.truetype(REF_FONT, size)


def font_name(lang: str) -> str:
    f = FONT_DIR / NOTO.get(lang, "")
    return f.stem if f.is_file() else "Arial Unicode"


def _missing(font, char: str) -> bool:
    """The font has no glyph for char (it would draw .notdef, the same box as a private-use code point)."""
    def r(c):
        im = Image.new("L", (300, 300), 0)
        ImageDraw.Draw(im).text((150, 150), c, font=font, fill=255, anchor="mm")
        return np.array(im)
    return np.array_equal(r(char), r("\ue000"))


@functools.lru_cache(maxsize=512)
def glyph_mask(lang: str, char: str) -> np.ndarray | None:
    """Target rendered in the matching Noto font for its script. Single code points only: without complex
    shaping, Devanagari conjuncts (स्ते) would render wrong, so those use the stroke template."""
    if len(char) != 1:
        return None
    font = _font(lang)
    if _missing(font, char):
        font = ImageFont.truetype(REF_FONT, 220)
    img = Image.new("L", (320, 320), 0)
    ImageDraw.Draw(img).text((160, 160), char, font=font, fill=255, anchor="mm")
    m = (np.array(img) > 127).astype(np.uint8) * 255
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _template_mask(lang: str, char: str) -> np.ndarray | None:
    try:
        tm = strokes.template(lang, char)
    except Exception:
        return None
    img = np.zeros((300, 300), np.uint8)
    for s in tm["strokes"]:
        cv2.polylines(img, [(s * 260 + 20).astype(np.int32)], False, 255, 14)
    if not img.any():
        return None
    ys, xs = np.nonzero(img)
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


@functools.lru_cache(maxsize=512)
def references(lang: str, char: str) -> tuple:
    """(name, skeleton points in [0,1] (aspect kept), aspect, components) for each reference."""
    out = []
    for name, m in (("font", glyph_mask(lang, char)), ("template", _template_mask(lang, char))):
        if m is None:
            continue
        sk = cv2.ximgproc.thinning(m)
        ys, xs = np.nonzero(sk)
        pts = np.stack([xs, ys], 1).astype(np.float32)
        n_comp = cv2.connectedComponents(m, connectivity=8)[0] - 1
        out.append((name, pts, m.shape[1] / max(1, m.shape[0]), n_comp))
    return tuple(out)


def _fit(pts: np.ndarray) -> np.ndarray:
    """Aspect-preserving fit into the canvas: the longer side spans FIT of it, centred."""
    lo, hi = pts.min(0), pts.max(0)
    ext = max(float((hi - lo).max()), 1e-6)
    return ((pts - (lo + hi) / 2) / ext * FIT + 0.5) * (S - 1)


def _raster(pts: np.ndarray) -> np.ndarray:
    img = np.zeros((S, S), np.uint8)
    p = np.clip(pts.round().astype(int), 0, S - 1)
    img[p[:, 1], p[:, 0]] = 255
    return img


def _grid(pts: np.ndarray) -> np.ndarray:
    lo, hi = pts.min(0), pts.max(0)
    rel = (pts - lo) / np.maximum(hi - lo, 1e-6)
    ix = np.clip((rel * 3).astype(int), 0, 2)
    g = np.zeros((3, 3), np.float32)
    np.add.at(g, (ix[:, 1], ix[:, 0]), 1)
    return g / max(1.0, g.sum())


_DIL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))


@functools.lru_cache(maxsize=1024)
def _ref_canvas(lang: str, char: str, idx: int):
    name, pts, aspect, n_comp = references(lang, char)[idx]
    fp = _fit(pts)
    r = _raster(fp)
    return {"name": name, "pts": fp, "dt": cv2.distanceTransform(255 - r, cv2.DIST_L2, 3),
            "mask": cv2.dilate(r, _DIL) > 0, "grid": _grid(pts), "aspect": aspect, "components": n_comp}


def _pose(pts: np.ndarray, deg: float, shear: float) -> np.ndarray:
    if not deg and not shear:
        return pts
    t = np.deg2rad(deg)
    M = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]], np.float32) @ np.array([[1, shear], [0, 1]], np.float32)
    c = pts.mean(0)
    return (pts - c) @ M.T + c


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def _compare(ink_pts: np.ndarray, ink_comp: int, ref: dict) -> dict:
    fp = _fit(ink_pts)
    r = _raster(fp)
    dt_ink = cv2.distanceTransform(255 - r, cv2.DIST_L2, 3)
    pi = np.clip(fp.round().astype(int), 0, S - 1)
    pr = np.clip(ref["pts"].round().astype(int), 0, S - 1)
    d_ink = ref["dt"][pi[:, 1], pi[:, 0]]   # ink → reference (stray marks)
    d_ref = dt_ink[pr[:, 1], pr[:, 0]]      # reference → ink (missing parts)
    chamfer = (float(d_ink.mean()) + float(d_ref.mean())) / 2 / S
    haus = max(float(np.percentile(d_ink, 95)), float(np.percentile(d_ref, 95))) / S
    m = cv2.dilate(r, _DIL) > 0
    iou = float((m & ref["mask"]).sum()) / max(1, int((m | ref["mask"]).sum()))
    grid = 1 - 0.5 * float(np.abs(_grid(ink_pts) - ref["grid"]).sum())
    lo, hi = ink_pts.min(0), ink_pts.max(0)
    aspect = max(1e-3, float(hi[0] - lo[0])) / max(1e-3, float(hi[1] - lo[1]))
    asp = float(np.exp(-1.5 * abs(np.log(max(aspect, 0.05) / max(ref["aspect"], 0.05)))))
    a, b = ink_comp, max(1, ref["components"])
    comp = 1 - min(1.0, abs(a - b) / max(a, b))
    tol = 0.06 * S
    m_ = {"iou": _clip01((iou - 0.05) / 0.5), "chamfer": _clip01(1 - chamfer / 0.12),
          "hausdorff": _clip01(1 - haus / 0.35), "grid": _clip01(grid), "aspect": asp, "components": comp}
    raw = sum(W[k] * v for k, v in m_.items())
    return {"raw": raw, "metrics": m_, "coverage": float((d_ref < tol).mean()), "precision": float((d_ink < tol).mean()),
            "chamfer": chamfer, "hausdorff": haus, "iou": iou, "ref": ref["name"]}


def _ink_points(mask: np.ndarray) -> tuple[np.ndarray, int]:
    sk = cv2.ximgproc.thinning(mask)
    ys, xs = np.nonzero(sk)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n = cv2.connectedComponents(closed, connectivity=8)[0] - 1
    return np.stack([xs, ys], 1).astype(np.float32), max(1, n)


def best_match(ink_pts: np.ndarray, ink_comp: int, lang: str, char: str, poses=POSES) -> dict | None:
    refs = references(lang, char)
    best = None
    for i in range(len(refs)):
        ref = _ref_canvas(lang, char, i)
        for deg, sh in poses:
            r = _compare(_pose(ink_pts, deg, sh), ink_comp, ref)
            if best is None or r["raw"] > best["raw"]:
                best = {**r, "pose": [deg, sh]}
    return best


def distractors(lang: str, char: str) -> list[str]:
    """Other characters the learner might have written instead: the rest of this script's lesson set."""
    seen, out = {char}, []
    lesson = content.load().get(lang) or {}
    for it in lesson.get("items") or []:
        for c in it.get("chars") or []:
            single = len(c) == 1 or (lang == "hindi" and len(c) <= 3)
            if c not in seen and single:
                seen.add(c)
                out.append(c)
    return out[:16]


def shape(mask: np.ndarray, lang: str, char: str) -> dict:
    """0-100 shape score + its parts. mask = the cropped ink."""
    t0 = time.perf_counter()
    pts, n_comp = _ink_points(mask)
    if len(pts) < 5:
        return {"score": 0, "raw": 0.0, "metrics": {}, "coverage": 0.0, "precision": 0.0, "ms": 0}
    tgt = best_match(pts, n_comp, lang, char)
    if tgt is None:
        return {"score": None, "raw": None, "metrics": {}, "coverage": None, "precision": None, "ms": 0,
                "error": "no reference for this character"}
    rivals = []
    tgt_len = len(references(lang, char)[0][1])
    for c in distractors(lang, char):
        refs = references(lang, c)
        if not refs or len(refs[0][1]) < 0.55 * tgt_len:
            continue  # a much simpler shape (ا, ι, 一) "fits" part of anything; not a fair rival
        r = best_match(pts, n_comp, lang, c, FEW_POSES)
        if r:
            rivals.append((r["raw"], c))
    rivals.sort(reverse=True)
    best_other, other_char = rivals[0] if rivals else (0.0, None)
    hi = RAW_HI_LANG.get(lang, RAW_HI)
    base = _clip01((tgt["raw"] - RAW_LO) / (hi - RAW_LO))
    margin = tgt["raw"] - best_other
    penalty = MARGIN_PENALTY * max(0.0, 0.005 - margin)  # another character fits better
    score = int(round(100 * _clip01(base - penalty)))
    return {"score": score, "raw": round(tgt["raw"], 3), "metrics": {k: round(v, 3) for k, v in tgt["metrics"].items()},
            "coverage": round(tgt["coverage"], 3), "precision": round(tgt["precision"], 3), "ref": tgt["ref"],
            "pose": tgt["pose"], "best_other": round(best_other, 3), "other_char": other_char,
            "margin": round(margin, 3), "ms": round((time.perf_counter() - t0) * 1000)}


# ------------------------------------------------------------------ 3. the rubric image

def rubric_image(gray_crop: np.ndarray, lang: str, char: str, side: int = 280) -> bytes:
    """Side-by-side JPEG: LEFT the learner's cropped writing (shadows removed), RIGHT the target glyph."""
    def square(a: np.ndarray) -> Image.Image:
        h, w = a.shape[:2]
        s = max(h, w)
        canvas = np.full((s, s), 255, np.uint8)
        canvas[(s - h) // 2:(s - h) // 2 + h, (s - w) // 2:(s - w) // 2 + w] = a
        return Image.fromarray(canvas).resize((side, side), Image.LANCZOS)
    left = square(gray_crop)
    g = glyph_mask(lang, char)
    if g is None:
        t = _template_mask(lang, char)
        g = t if t is not None else np.zeros((10, 10), np.uint8)
    pad = int(0.15 * max(g.shape))
    ref = np.pad(255 - g, pad, constant_values=255)
    right = square(ref)
    out = Image.new("L", (side * 2 + 12, side + 30), 255)
    out.paste(left, (0, 30))
    out.paste(right, (side + 12, 30))
    d = ImageDraw.Draw(out)
    d.line([(side + 6, 0), (side + 6, side + 30)], fill=160, width=2)
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
    except Exception:
        f = None
    d.text((8, 5), "LEFT: learner's handwriting", fill=0, font=f)
    d.text((side + 20, 5), "RIGHT: target", fill=0, font=f)
    buf = io.BytesIO()
    out.convert("RGB").save(buf, "JPEG", quality=88)
    return buf.getvalue()


def crop_jpeg(gray_crop: np.ndarray) -> bytes:
    return cv2.imencode(".jpg", gray_crop, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()


def raw_for(mask: np.ndarray, lang: str, char: str) -> float | None:
    """Raw shape similarity of the ink to `char` (used to check the rubric's reading)."""
    pts, n_comp = _ink_points(mask)
    if len(pts) < 5 or not references(lang, char):
        return None
    r = best_match(pts, n_comp, lang, char)
    return r["raw"] if r else None
