"""Tier 1 reference: "is there a new stroke since the last photo?"

The iPhone (agent D) runs tier 1 on-device; this is the same algorithm server-side, used as
POST /ink-diff (fallback) and as the tested reference for the parameters D should use:
  1. align AFTER onto BEFORE (ECC, euclidean: shift + small rotation), so camera wobble isn't ink
  2. extract ink in both with strokes.extract_ink (lighting-normalized, ignores ruled lines,
     shadows, holes, spiral binding)
  3. new ink = after_ink minus a dilated before_ink (tolerates 1-2 px misalignment and pen-width
     variation), then drop specks; "new stroke" needs NEW_MIN_FRAC of the image area."""

from __future__ import annotations

import time

import cv2
import numpy as np

from . import strokes

ALIGN_SIDE = 320
NEW_MIN_FRAC = 0.0004   # new ink must cover at least this fraction of the image
DILATE_PX = 5           # tolerance around existing ink


def _align(before: np.ndarray, after: np.ndarray) -> tuple[np.ndarray, bool]:
    """Warp `after` onto `before`. Returns (warped_after, aligned_ok)."""
    h, w = before.shape[:2]
    scale = ALIGN_SIDE / max(h, w)
    small = lambda im: cv2.resize(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (int(w * scale), int(h * scale)),
                                  interpolation=cv2.INTER_AREA).astype(np.float32)
    a, b = small(before), small(after)
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_EUCLIDEAN,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-4), None, 5)
    except cv2.error:
        return after, False
    warp[:, 2] /= scale
    out = cv2.warpAffine(after, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_REPLICATE)
    return out, True


def diff(before_raw: bytes, after_raw: bytes) -> dict:
    t0 = time.perf_counter()
    before = strokes.decode(before_raw)
    after = strokes.decode(after_raw)
    if after.shape != before.shape:
        after = cv2.resize(after, (before.shape[1], before.shape[0]), interpolation=cv2.INTER_AREA)
    after_al, aligned = _align(before, after)
    ink_b = strokes.extract_ink(before)
    ink_a = strokes.extract_ink(after_al)
    grown = cv2.dilate(ink_b, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * DILATE_PX + 1,) * 2))
    new = cv2.bitwise_and(ink_a, cv2.bitwise_not(grown))
    new = cv2.morphologyEx(new, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    h, w = new.shape
    n, labels, stats, _ = cv2.connectedComponentsWithStats(new, 8)
    keep = np.zeros_like(new)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= max(6, int(h * w * 0.00005)):
            keep[labels == i] = 255
    area = int((keep > 0).sum())
    frac = area / float(h * w)
    bbox = None
    if area:
        ys, xs = np.nonzero(keep)
        bbox = [round(xs.min() / w, 4), round(ys.min() / h, 4), round(xs.max() / w, 4), round(ys.max() / h, 4)]
    return {"new_stroke": frac >= NEW_MIN_FRAC, "new_ink_frac": round(frac, 6), "bbox": bbox,
            "aligned": aligned, "ms": int((time.perf_counter() - t0) * 1000)}
