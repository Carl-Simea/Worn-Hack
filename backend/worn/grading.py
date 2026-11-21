"""The measured grade: 60% shape score (worn/measure.py) + 40% Scribi's rubric (qwen2.5vl on the crop).

Returns {status: ok|no_writing, score 0-100 (None if no writing), correct (score >= 70), subscores{5 × 0-100},
feedback (names the weakest sub-score + one fix), crop (jpeg bytes), crop_box [x,y,w,h], shape{...},
rubric{...}, seen, ms{find,shape,rubric,total}}.
"""

from __future__ import annotations

import asyncio
import logging
import time

from . import config, measure, scripts, vision

log = logging.getLogger("worn.grading")

SHAPE_W, RUBRIC_W = 0.6, 0.4
PASS = 70
RUBRIC_LO, RUBRIC_HI = 15.0, 50.0  # calibrated in eval_grading.py (REMAINING-A.md)
RUBRIC_TIMEOUT = float(__import__('os').environ.get('WORN_RUBRIC_TIMEOUT', '5.0'))
# rubric sub-score weights (0-10 each → 0-100)
RW = {"recognizable": 0.35, "proportions": 0.15, "stroke_placement": 0.2, "completeness": 0.2, "neatness": 0.1}
NO_WRITING = "I can't see your writing. Hold the paper flat, about 30 cm away."
LABEL = {"recognizable": "how recognizable it is", "proportions": "proportions", "placement": "stroke placement",
         "completeness": "completeness", "neatness": "neatness"}
TIP = {"recognizable": "Watch the strokes once more and copy the overall shape.",
       "proportions": "Match the height and width of the model.",
       "placement": "Check where each part sits relative to the others.",
       "completeness": "Some strokes are missing. Count them against the model.",
       "neatness": "Lift the pen cleanly between strokes."}


def _step(progress, i: int) -> None:
    if progress:
        try:
            progress(i)
        except Exception:
            pass


async def grade(jpeg: bytes, char: str, lang: str, progress=None, romanization: str | None = None) -> dict:
    t0 = time.perf_counter()
    _step(progress, 0)  # finding your writing
    fw = await asyncio.to_thread(measure.find_writing, jpeg)
    t_find = (time.perf_counter() - t0) * 1000
    if fw is None:
        return {"status": "no_writing", "score": None, "correct": False, "subscores": None, "feedback": NO_WRITING,
                "crop": None, "crop_box": None, "shape": None, "rubric": None, "seen": "",
                "ms": {"find": round(t_find), "total": round((time.perf_counter() - t0) * 1000)}}
    _step(progress, 1)  # comparing strokes
    board = measure.rubric_image(fw["gray"], lang, char)

    async def _rubric():
        try:
            return await asyncio.wait_for(vision.rubric(board, char, lang, romanization), RUBRIC_TIMEOUT)
        except Exception as e:
            log.warning("rubric unavailable: %r", e)
            return None, {"error": f"{type(e).__name__}: {str(e)[:80]}"}

    t1 = time.perf_counter()
    rub_task = asyncio.create_task(_rubric())
    shp = await asyncio.to_thread(measure.shape, fw["mask"], lang, char)
    t_shape = (time.perf_counter() - t1) * 1000
    _step(progress, 2)  # Scribi is reviewing
    rub, rmeta = await rub_task
    t_rub = (time.perf_counter() - t1) * 1000

    shape_score = shp["score"] if shp.get("score") is not None else 50
    m = shp.get("metrics") or {}
    if rub:
        seen = rub.get("seen") or ""
        other_letter = (len(seen) == 1 and seen != char and lang in scripts._RANGES and scripts.in_script(seen, lang)
                        and vision._base(seen).casefold() != vision._base(char).casefold())
        if other_letter and shp.get("margin", 0) < 0.03:
            rub = {**rub, "recognizable": min(rub["recognizable"], 2)}  # reads as a different letter, shape agrees
        elif other_letter and shp.get("margin", 0) >= 0.1 and shape_score >= 70:
            rub = {**rub, "recognizable": max(rub["recognizable"], 6)}  # look-alike misread; the strokes say target
        rubric_raw = 10 * sum(RW[k] * rub[k] for k in RW)
        # qwen2.5vl's rubric is harsh and compressed (good ≈ 46, wrong ≈ 31 raw); rescaled on the calibration set
        rubric_score = max(0.0, min(100.0, (rubric_raw - RUBRIC_LO) / (RUBRIC_HI - RUBRIC_LO) * 100))
        r10 = {k: rub[k] * 10 for k in RW}
    else:
        rubric_score, r10, seen = None, {}, ""
    guard = None
    if rub is not None and shape_score >= 75 and rubric_score < 60:
        # the strokes clearly match the target and nothing else: the vision model misreads unfamiliar scripts
        rubric_score, guard = 60.0, "shape-confident"
    final = shape_score if rubric_score is None else SHAPE_W * shape_score + RUBRIC_W * rubric_score
    if shp.get("score") is not None and shape_score < 30:
        final, guard = min(final, 35), "shape says not the target"  # the rubric can't rescue it (echo guard)
    if rub and seen and len(seen) == 1 and seen != char and seen.casefold() != char.casefold() \
            and vision._base(seen) != vision._base(char) and lang in scripts._RANGES and scripts.in_script(seen, lang):
        alt = await asyncio.to_thread(measure.raw_for, fw["mask"], lang, seen)
        if alt is not None and shp.get("raw") is not None and alt >= shp["raw"] - 0.02:
            final, guard = min(final, 35), f"reads as {seen} and the strokes agree"
    score = int(round(max(0, min(100, final))))

    def blend(measured: float | None, rk: str) -> int:
        vals = [v for v in (None if measured is None else 100 * measured, r10.get(rk)) if v is not None]
        return int(round(sum(vals) / len(vals))) if vals else 0
    subscores = {
        "recognizable": int(round(r10["recognizable"])) if r10 else shape_score,
        "proportions": blend(m.get("aspect"), "proportions"),
        "placement": blend(m.get("grid"), "stroke_placement"),
        "completeness": blend(shp.get("coverage"), "completeness"),
        "neatness": blend(shp.get("precision"), "neatness"),
    }
    weakest = min(subscores, key=lambda k: subscores[k])
    fix = (rub or {}).get("fix") or TIP[weakest]
    correct = score >= PASS
    if correct and score >= 90:
        feedback = f"Excellent {char}!" + (f" Tiny polish: {fix}" if (rub or {}).get("fix") else "")
    elif correct:
        feedback = f"Good {char}! Weakest: {LABEL[weakest]} ({subscores[weakest]}). {fix}"
    else:
        feedback = f"Work on {LABEL[weakest]} ({subscores[weakest]}): {fix}"
    return {"status": "ok", "score": score, "correct": correct, "subscores": subscores, "weakest": weakest,
            "feedback": feedback, "crop": measure.crop_jpeg(fw["gray"]), "crop_box": fw["box"], "frame": fw["frame"],
            "deskew_deg": fw["angle"], "seen": seen, "guard": guard,
            "shape": {k: shp.get(k) for k in ("score", "raw", "metrics", "coverage", "precision", "ref", "margin",
                                              "other_char", "ms")},
            "rubric": ({**{k: rub[k] for k in RW}, "score": round(rubric_score), "raw": round(rubric_raw), "fix": rub.get("fix"),
                        "seen": seen, "ms": rmeta.get("ms")} if rub else {"error": rmeta.get("error")}),
            "ms": {"find": round(t_find), "shape": round(t_shape), "rubric": round(t_rub),
                   "total": round((time.perf_counter() - t0) * 1000)},
            "model": config.VISION_MODEL if rub else None}
