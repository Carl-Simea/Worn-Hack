"""Tier 2 perception: stroke templates + OpenCV ink matching (target < 300 ms).

Templates, in a y-down square frame:
  mandarin: hanzi-writer medians (1024 grid, y up), true stroke order.
  svg (content/strokes/{lang}/*.svg, 109 grid): centerline paths, one <path> per stroke. The team's
    hand-authored files say "suggested" and are labeled that way (ordered=False: we don't claim
    a canonical order for them).
  anything else: the glyph is rendered from a system font, thinned to a skeleton and treated as
    ONE "trace the shape" stroke.

Matching: the photo's ink is thresholded, cleaned, thinned to a skeleton, normalized to a unit
box and compared to the template points with a symmetric chamfer distance on a raster."""

from __future__ import annotations

import functools
import io
import json
import logging
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import config

log = logging.getLogger("worn.strokes")

GRID = 128  # raster size for the distance transform
DONE_SCORE = 45  # minimum match for a stroke to count (plus the relative test)
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/DevanagariMT.ttc",
    "/System/Library/Fonts/Supplemental/GeezaPro.ttc",
]
EXTS = ("svg", "gif", "webm", "mp4", "json")


def _hex(char: str) -> str:
    return "-".join(f"{ord(c):x}" for c in char)


def stroke_file(lang: str, char: str):
    for ext in EXTS:
        p = config.CONTENT_DIR / "strokes" / lang / f"{_hex(char)}.{ext}"
        if p.exists():
            return p
    return None


def stroke_url(lang: str, char: str | None) -> str | None:
    if not char:
        return None
    p = stroke_file(lang, char)
    return f"/static/content/strokes/{lang}/{p.name}" if p else None


def stroke_count(lang: str, char: str | None) -> int:
    if not char:
        return 0
    try:
        return len(template(lang, char)["strokes"])
    except Exception:
        return 1


# ------------------------------------------------------------------ templates

def _densify(pts: np.ndarray, step: float = 0.01) -> np.ndarray:
    """Resample a polyline so points are ~step apart (unit coords)."""
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(np.linalg.norm(b - a) / step))
        for t in np.linspace(0, 1, n + 1)[1:]:
            out.append(a + (b - a) * t)
    return np.array(out, dtype=np.float32)


def _cubic(p0, p1, p2, p3, n=12):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


_TOK = re.compile(r"[MmCcSsLlHhVvZz]|-?\d*\.?\d+(?:e-?\d+)?")


def parse_svg_path(d: str) -> np.ndarray:
    """Polyline for an SVG path using M/C/S/L/H/V/Z (absolute + relative)."""
    toks = _TOK.findall(d)
    pts: list[np.ndarray] = []
    cur = np.zeros(2)
    start = np.zeros(2)
    last_ctrl = None
    cmd = None
    i = 0

    def num():
        nonlocal i
        v = float(toks[i]); i += 1
        return v

    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]; i += 1
            if cmd in "Zz":
                pts.append(start.copy()); cur = start.copy()
                continue
        rel = cmd.islower()
        base = cur if rel else np.zeros(2)
        c = cmd.upper()
        if c == "M":
            cur = base + np.array([num(), num()]); start = cur.copy(); pts.append(cur.copy())
            cmd = "l" if rel else "L"  # implicit lineto after moveto
            last_ctrl = None
        elif c == "L":
            cur = base + np.array([num(), num()]); pts.append(cur.copy()); last_ctrl = None
        elif c == "H":
            x = num(); cur = np.array([cur[0] + x if rel else x, cur[1]]); pts.append(cur.copy())
        elif c == "V":
            y = num(); cur = np.array([cur[0], cur[1] + y if rel else y]); pts.append(cur.copy())
        elif c == "C":
            p1 = base + np.array([num(), num()]); p2 = base + np.array([num(), num()]); p3 = base + np.array([num(), num()])
            pts.extend(_cubic(cur, p1, p2, p3)[1:]); last_ctrl = p2; cur = p3
        elif c == "S":
            p1 = 2 * cur - last_ctrl if last_ctrl is not None else cur
            p2 = base + np.array([num(), num()]); p3 = base + np.array([num(), num()])
            pts.extend(_cubic(cur, p1, p2, p3)[1:]); last_ctrl = p2; cur = p3
        else:
            i += 1  # unsupported command: skip a number rather than loop forever
    return np.array(pts, dtype=np.float32)


def _font():
    for f in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(f, 200)
        except Exception:
            continue
    return None


def _glyph_skeleton_points(char: str) -> np.ndarray:
    font = _font()
    if font is None:
        raise RuntimeError("no font with this script available")
    img = Image.new("L", (300, 300), 0)
    ImageDraw.Draw(img).text((150, 150), char, font=font, fill=255, anchor="mm")
    mask = np.array(img)
    if mask.max() == 0:
        raise RuntimeError(f"font cannot render {char!r}")
    skel = cv2.ximgproc.thinning((mask > 127).astype(np.uint8) * 255)
    ys, xs = np.nonzero(skel)
    return np.stack([xs, ys], axis=1).astype(np.float32) / 300.0


def template(lang: str, char: str) -> dict:
    """{"strokes": [Nx2 arrays in a y-down frame], "source": ...}. Cached per file version, so
    edits under content/strokes take effect without a restart."""
    f = stroke_file(lang, char)
    return _template(lang, char, str(f) if f else "", f.stat().st_mtime if f else 0.0)


@functools.lru_cache(maxsize=1024)
def _template(lang: str, char: str, path: str, mtime: float) -> dict:
    from pathlib import Path
    f = Path(path) if path else None
    if f is not None and f.suffix == ".json":
        data = json.loads(f.read_text(encoding="utf-8"))
        strokes = []
        for med in data["medians"]:
            a = np.array(med, dtype=np.float32)
            a[:, 1] = 900 - a[:, 1]  # hanzi-writer: y up, baseline 900
            strokes.append(_densify(a / 1024.0))
        return {"strokes": strokes, "source": "hanzi-writer medians", "ordered": True}
    if f is not None and f.suffix == ".svg":
        svg = f.read_text(encoding="utf-8")
        ds = re.findall(r'<path[^>]*\sd="([^"]+)"', svg)
        if ds:
            suggested = "suggested" in svg.lower()
            return {"strokes": [_densify(parse_svg_path(d) / 109.0) for d in ds],
                    "source": "suggested stroke order" if suggested else "SVG stroke order",
                    "ordered": not suggested}
    return {"strokes": [_glyph_skeleton_points(char)], "source": "font skeleton (trace the shape)", "ordered": False,
            "trace": True}


# ------------------------------------------------------------------ ink

WORK_SIDE = 1024  # ink detection resolution: thin pen lines vanish at 640 px on whole-page photos


def decode(raw: bytes, max_side: int = WORK_SIDE) -> np.ndarray:
    """Bytes -> BGR image, EXIF-rotated, max side max_side."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    img.thumbnail((max_side, max_side))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def paper_background(gray: np.ndarray) -> np.ndarray:
    """Local paper brightness: a large grayscale closing removes dark thin marks (ink, ruled
    lines), leaving the paper and its shadows. Computed at 1/4 scale for speed."""
    h, w = gray.shape
    small = cv2.resize(gray, (max(8, w // 4), max(8, h // 4)), interpolation=cv2.INTER_AREA)
    k = max(9, (min(small.shape) // 12) | 1)
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.medianBlur(bg, 5)
    return cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)


# Ink vs paper brightness (pixel / local paper). Measured on the 3 teammate notebook photos in
# test_data/handwriting: pen ink 0.37-0.69, darkest ruled-line pixels >= 0.74. Hysteresis: a
# stroke needs a seed darker than INK_STRONG and then grows through pixels darker than INK_WEAK.
INK_STRONG = 0.58
INK_WEAK = 0.70


def extract_ink(bgr: np.ndarray) -> np.ndarray:
    """Binary mask (uint8 0/255) of pen ink, robust to real notebook photos:
    - shadows / uneven light: compare each pixel to the LOCAL paper brightness, not a global level
    - ruled lines and the red margin: much lighter than pen ink relative to the paper, so they fail INK_RATIO
    - desk, spiral binding, page edge: outside the paper mask or touching the image border
    - hole punches: solid, round, thick blobs, unlike pen strokes
    - specks: too small"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    h, w = gray.shape
    bg = paper_background(gray).astype(np.float32)
    ratio = gray.astype(np.float32) / np.maximum(bg, 1)
    weak = (ratio < INK_WEAK).astype(np.uint8) * 255
    strong = ratio < INK_STRONG

    # Paper = bright, smooth background. Ink must sit on it (spiral rings and the desk don't).
    bright = float(np.percentile(bg, 90))
    paper = (bg > 0.55 * bright).astype(np.uint8)
    paper = cv2.erode(paper, np.ones((9, 9), np.uint8))
    weak[paper == 0] = 0
    # Ruled lines touching a letter would be "grown" into it as horizontal spurs. Remove long thin
    # horizontal runs made only of faint pixels; pen strokes (even horizontal ones) are dark enough
    # to be strong, so they are never removed here.
    faint = cv2.bitwise_and(weak, cv2.bitwise_not(strong.astype(np.uint8) * 255))
    run = max(15, w // 40)
    lines = cv2.morphologyEx(faint, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (run, 1)))
    lines = cv2.dilate(lines, np.ones((3, 1), np.uint8))
    weak = cv2.bitwise_and(weak, cv2.bitwise_not(cv2.bitwise_and(lines, faint)))
    nw, wl = cv2.connectedComponents(weak, connectivity=8)
    seeded = np.zeros(nw, bool)
    seeded[np.unique(wl[strong & (wl > 0)])] = True
    seeded[0] = False
    mask = seeded[wl].astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return np.zeros_like(mask)
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    min_area = max(10, int(h * w * 0.00003))
    cand = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches = x <= 2 or y <= 2 or x + bw >= w - 2 or y + bh >= h - 2
        sparse_long = (bw > 0.6 * w or bh > 0.6 * h) and area < 0.08 * bw * bh  # page edge, long line
        if area < min_area or touches:
            continue
        comp = labels[y:y + bh, x:x + bw] == i
        if sparse_long and float(strong[y:y + bh, x:x + bw][comp].mean()) < 0.5:
            continue  # faint and long: a ruled line or the page edge. A dark pen stroke filling the frame stays.
        thick = float(dist[y:y + bh, x:x + bw][comp].max())
        cand.append((i, x, y, bw, bh, area, thick))
    if not cand:
        return np.zeros_like(mask)
    pen = float(np.median([c[6] for c in cand]))  # typical half-width of a pen stroke here
    spiral = _binding_columns(cand, w, h)
    keep = np.zeros_like(mask)
    for i, x, y, bw, bh, area, thick in cand:
        if i in spiral:
            continue
        # Spiral rings, hole-punch shadows and blots are much thicker than this photo's pen strokes.
        # Relative to the median, so a close-up written with a thick marker still passes.
        if len(cand) > 2 and thick > 2.2 * max(pen, 1.0):
            continue
        keep[labels == i] = 255
    if pen >= 2.5:
        # Hairline stubs (bits of ruled line touching a thick stroke) wreck the shape match; a 3x3
        # opening removes them. Only when the pen is clearly thicker than a hair, so fine-pen
        # whole-page photos keep every stroke.
        keep = cv2.morphologyEx(keep, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return keep


def _binding_columns(cand: list, w: int, h: int) -> set[int]:
    """Spiral binding: many components stacked in a narrow vertical band near the left or right
    edge, spanning a good part of the page height. Handwriting doesn't look like that."""
    out: set[int] = set()
    for side in ("left", "right"):
        comps = [c for c in cand if ((c[1] + c[3] / 2) < 0.18 * w if side == "left" else (c[1] + c[3] / 2) > 0.82 * w)]
        if len(comps) < 6:
            continue
        xs = np.array([c[1] + c[3] / 2 for c in comps])
        for cx in xs:
            band = [c for c, x in zip(comps, xs) if abs(x - cx) < 0.05 * w]
            ys = [c[2] for c in band] + [c[2] + c[4] for c in band]
            if len(band) >= 6 and (max(ys) - min(ys)) > 0.25 * h:
                out.update(c[0] for c in band)
    return out


def ink_points(mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return np.zeros((0, 2), np.float32)
    skel = cv2.ximgproc.thinning(mask)
    ys, xs = np.nonzero(skel)
    return np.stack([xs, ys], axis=1).astype(np.float32)


# ------------------------------------------------------------------ matching

def _normalize(pts: np.ndarray) -> np.ndarray:
    """Fit points into [0.05, 0.95]. Each axis is stretched on its own (handwriting proportions
    vary a lot), except for nearly 1-D shapes like a single straight stroke, which keep aspect."""
    lo, hi = pts.min(0), pts.max(0)
    ext = np.maximum(hi - lo, 1e-6)
    if ext.min() < 0.3 * ext.max():
        ext = np.full(2, ext.max())
    return (pts - (lo + hi) / 2) / ext * 0.9 + 0.5


def _transform(pts: np.ndarray, deg: float, shear: float) -> np.ndarray:
    """Rotate by deg and shear horizontally (x += shear * y) around the centroid."""
    if not deg and not shear:
        return pts
    t = np.deg2rad(deg)
    rot = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]], dtype=np.float32)
    sh = np.array([[1, shear], [0, 1]], dtype=np.float32)
    c = pts.mean(0)
    return (pts - c) @ (rot @ sh).T + c


def _raster(pts: np.ndarray) -> np.ndarray:
    img = np.full((GRID, GRID), 255, np.uint8)
    p = np.clip((pts * (GRID - 1)).round().astype(int), 0, GRID - 1)
    img[p[:, 1], p[:, 0]] = 0
    return img


def _chamfer_once(ink: np.ndarray, tmpl: np.ndarray) -> tuple[float, float]:
    """(score 0-100, coverage 0-1). coverage = share of template points with ink nearby."""
    a, b = _normalize(ink), _normalize(tmpl)
    da = cv2.distanceTransform(_raster(b), cv2.DIST_L2, 3)  # distance to template
    db = cv2.distanceTransform(_raster(a), cv2.DIST_L2, 3)  # distance to ink
    pa = np.clip((a * (GRID - 1)).round().astype(int), 0, GRID - 1)
    pb = np.clip((b * (GRID - 1)).round().astype(int), 0, GRID - 1)
    d_ink = float(np.mean(da[pa[:, 1], pa[:, 0]]))  # ink far from template = extra marks
    tmpl_d = db[pb[:, 1], pb[:, 0]]
    d_tmp = float(np.mean(tmpl_d))  # template far from ink = missing parts
    d = (d_ink + d_tmp) / 2 / GRID
    coverage = float(np.mean(tmpl_d < 0.07 * GRID))
    return float(max(0.0, min(100.0, 100.0 * (1 - d / 0.11)))), coverage


# Camera tilt and handwriting slant: the ink is un-tilted / un-slanted before comparing.
# Slanted (cursive-ish) writing is mostly a horizontal shear, which rotation alone can't undo.
POSES = [(a, s) for a in (-10, -5, 0, 5, 10) for s in (-0.3, 0.0, 0.3)]


def chamfer_detail(ink: np.ndarray, tmpl: np.ndarray) -> tuple[float, float]:
    """Best (score, coverage) over a few small rotations and slants of the ink."""
    if len(ink) < 3 or len(tmpl) < 2:
        return 0.0, 0.0
    return max((_chamfer_once(_transform(ink, a, s), tmpl) for a, s in POSES), key=lambda r: r[0])


def chamfer_score(ink: np.ndarray, tmpl: np.ndarray) -> float:
    """0-100. Symmetric mean distance between two point sets after normalization."""
    return chamfer_detail(ink, tmpl)[0]


MIN_COVERAGE = 0.7  # most of strokes 0..k must have ink near them


def match_stroke(raw: bytes, lang: str, char: str, stroke_index: int, diff: bool = False) -> dict:
    """Tier 2. Is stroke k (0-based) on the paper now?

    Default: the image shows the whole character so far. Stroke k counts as done when the ink
    matches strokes 0..k reasonably (>= DONE_SCORE) AND better than it matches strokes 0..k-1,
    i.e. adding stroke k to the template explains the ink better. This relative test holds up
    across handwriting styles much better than an absolute threshold.
    diff=True: the image is ONLY the new ink (the iPhone's tier-1 diff), compared to stroke k alone."""
    tm = template(lang, char)
    strokes = tm["strokes"]
    total = len(strokes)
    k = max(0, min(stroke_index, total - 1))
    pts = ink_points(extract_ink(decode(raw)))
    base = {"stroke_index": k, "stroke_count": total, "template": tm["source"], "ordered": tm["ordered"]}
    if len(pts) < 3:
        return {**base, "score": 0, "done": False, "next_stroke_index": k, "char_done": False,
                "ink": False, "hint": "I don't see new ink yet."}
    if diff:
        score = chamfer_score(pts, strokes[k])
        done = score >= DONE_SCORE
    else:
        score, coverage = chamfer_detail(pts, np.concatenate(strokes[: k + 1]))
        prev = chamfer_score(pts, np.concatenate(strokes[:k])) if k > 0 else 0.0
        # The last stroke is often small (a dot, a short tick), so at the end a tie with
        # strokes 0..k-1 still counts when the whole-character match is solid.
        last = k == total - 1
        done = (score >= DONE_SCORE and coverage >= MIN_COVERAGE
                and (score > prev or (last and score >= 55 and score >= prev - 3)))
    score = int(round(score))
    char_done = done and k == total - 1
    if done:
        hint = "Character complete!" if char_done else f"Stroke {k + 1} done. Now stroke {k + 2}."
    elif total == 1:
        hint = "Keep tracing the shape."
    else:
        hint = f"Stroke {k + 1} isn't there yet. Watch it again."
    return {**base, "score": score, "done": done, "next_stroke_index": min(k + 1, total - 1) if done else k,
            "char_done": char_done, "ink": True, "hint": hint}


def compare_full(raw: bytes, lang: str, char: str) -> dict:
    """Whole-character template similarity (the agent's compare_to_template tool)."""
    tm = template(lang, char)
    pts = ink_points(extract_ink(decode(raw)))
    score = chamfer_score(pts, np.concatenate(tm["strokes"])) if len(pts) >= 3 else 0.0
    return {"score": int(round(score)), "ink": len(pts) >= 3, "template": tm["source"],
            "stroke_count": len(tm["strokes"])}
