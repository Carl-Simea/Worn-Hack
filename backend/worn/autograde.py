"""Automatic, continuous grading from the camera preview frames (no "check" needed).

Per preview frame (newest only, at most every MIN_INTERVAL; frames that arrive while one is being
processed are skipped):
  1. tier-1 ink diff against the last frame that had new ink (camera wobble, light and ruled lines are
     ignored; a hand covering the page is "occluded" and ignored)
  2. on new ink: a fast shape-only score of the strokes so far vs. the reference up to the current stroke
     (tier 2, no LLM, ~10-30 ms) → /app-state grading.phase "stroke_scored" {stroke, stroke_count, accuracy}
  3. auto-final when the last stroke is matched OR the ink hasn't changed for SETTLE_S: phase "analyzing".
     The glasses are asked for a full-res still (/app-state grading.capture_request); if none arrives within
     STILL_WAIT_S, the newest preview frame is graded instead. "check" by voice stays a manual override.
Phases: idle → watching → stroke_scored → analyzing (steps) → result.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import time
from typing import Awaitable, Callable

from . import inkdiff, strokes
from . import voice as V
from .live import LIVE

log = logging.getLogger("worn.autograde")

MIN_INTERVAL = float(os.environ.get("WORN_AUTO_INTERVAL", "0.2"))
SETTLE_S = float(os.environ.get("WORN_AUTO_SETTLE", "2.0"))
STILL_WAIT_S = float(os.environ.get("WORN_AUTO_STILL_WAIT", "1.2"))
OCCLUDE_FRAC = 0.04  # "new ink" over 4% of the frame at once is a hand or the pen holder, not a stroke
ENABLED = os.environ.get("WORN_AUTO_GRADE", "1") != "0"

ANALYZE_STEPS = ["finding your writing", "comparing strokes", "Scribi is reviewing"]
_req_ids = itertools.count(1)


class AutoGrader:
    def __init__(self) -> None:
        self.grade_fn: Callable[[bytes, str], Awaitable[dict]] | None = None  # set by app: (jpeg, source)
        self.reset()

    def reset(self) -> None:
        self.key = None
        self.baseline: bytes | None = None
        self.latest: bytes | None = None
        self.stroke = 0
        self.total = 0
        self.scores: list[int | None] = []
        self.last_change: float | None = None
        self.final_started = False
        self.busy = False
        self.last_run = 0.0
        self.still_event: asyncio.Event | None = None
        self.request: dict | None = None
        self.settle_task: asyncio.Task | None = None

    # ------------------------------------------------------------- state out

    def publish(self, phase: str, **extra) -> None:
        g = {"phase": phase, "stroke": self.stroke + (1 if phase == "stroke_scored" else 0),
             "stroke_count": self.total, "stroke_scores": list(self.scores),
             "accuracy": extra.pop("accuracy", None), "ts": time.time(), **extra}
        V.update_state({"grading": g, "grade_phase": phase}, source="autograde")
        LIVE.bump()

    # ------------------------------------------------------------- frames in

    def _session_key(self):
        s = LIVE.session
        if not s or V.get_state().get("screen") not in ("lesson", None):
            return None
        return (s.get("lang"), s.get("char"), s.get("char_index"), s.get("version"))

    async def on_frame(self, jpeg: bytes, meta: dict) -> None:
        if not ENABLED:
            return
        self.latest = jpeg
        now = time.time()
        if self.busy or now - self.last_run < MIN_INTERVAL:
            return
        key = self._session_key()
        if key is None:
            self.key, self.baseline = None, jpeg
            return
        if key != self.key:  # new character: this frame is the blank-paper baseline
            self.reset_for(key, jpeg)
            return
        if self.final_started:
            return
        self.busy, self.last_run = True, now
        try:
            await self._process(jpeg)
        except Exception as e:
            log.warning("auto-grade frame failed: %s", e)
        finally:
            self.busy = False

    def reset_for(self, key, jpeg: bytes) -> None:
        grade_fn = self.grade_fn
        if self.settle_task:
            self.settle_task.cancel()
        self.reset()
        self.grade_fn = grade_fn
        self.key, self.baseline, self.latest = key, jpeg, jpeg
        s = LIVE.session or {}
        self.total = int(s.get("stroke_count") or strokes.stroke_count(s.get("lang"), s.get("char")) or 1)
        self.scores = [None] * self.total
        self.publish("watching")

    async def _process(self, jpeg: bytes) -> None:
        d = await asyncio.to_thread(inkdiff.diff, self.baseline, jpeg)
        LIVE.latency("tier1", d["ms"])
        if d["new_ink_frac"] > OCCLUDE_FRAC:
            return  # hand over the page: wait for it to move
        if not d["new_stroke"]:
            return
        self.baseline = jpeg
        self.last_change = time.time()
        s = LIVE.session or {}
        t = time.perf_counter()
        m = await asyncio.to_thread(strokes.match_stroke, jpeg, s["lang"], s["char"], self.stroke)
        ms = (time.perf_counter() - t) * 1000
        LIVE.latency("tier2", ms)
        k = m["stroke_index"]
        self.scores[k] = m["score"]
        done_stroke = m["done"]
        self.publish("stroke_scored", accuracy=m["score"], stroke_done=done_stroke, char_done=m["char_done"],
                     hint=m["hint"], ms=round(ms))
        LIVE.set_stroke(k + 1 if done_stroke else k, self.total)
        LIVE.add_step("auto", "evaluate", f"Stroke {k + 1}/{self.total}: {m['score']}% "
                      + ("done" if done_stroke else "in progress"), tool="t2", ms=ms,
                      data={"score": m["score"], "stroke_index": k, "done": done_stroke})
        if done_stroke and not m["char_done"]:
            self.stroke = min(k + 1, self.total - 1)
        if m["char_done"]:
            await self.final("all strokes done")
            return
        if self.settle_task:
            self.settle_task.cancel()
        self.settle_task = asyncio.create_task(self._settle(self.last_change))

    async def _settle(self, since: float) -> None:
        await asyncio.sleep(SETTLE_S)
        if self.last_change == since and not self.final_started:
            await self.final(f"ink still for {SETTLE_S:g}s")

    # ------------------------------------------------------------- final grade

    async def final(self, reason: str, manual: bool = False) -> dict | None:
        if self.final_started and not manual:
            return None
        self.final_started = True
        rid = next(_req_ids)
        self.request = {"id": rid, "ts": time.time(), "reason": reason}
        self.still_event = asyncio.Event()
        self.publish("analyzing", step=0, step_label=ANALYZE_STEPS[0], steps=ANALYZE_STEPS, reason=reason,
                     capture_request=self.request)
        LIVE.add_event("autograde", {"reason": reason, "request": rid})
        try:
            await asyncio.wait_for(self.still_event.wait(), STILL_WAIT_S)
            return None  # the glasses sent a full-res still to /grade, which grades it
        except asyncio.TimeoutError:
            pass
        if self.grade_fn is None or self.latest is None:
            return None
        try:
            return await self.grade_fn(self.latest, "preview")
        except Exception as e:
            log.warning("auto-grade final failed: %s", e)
            self.publish("result", error=str(e)[:120])
            return None

    def still_arrived(self) -> dict | None:
        """/grade got a photo: satisfies a pending capture request. Returns the request (or None)."""
        req = self.request
        if self.still_event and not self.still_event.is_set():
            self.still_event.set()
        self.final_started = True
        return req

    def analyzing(self, step: int) -> None:
        self.publish("analyzing", step=step, step_label=ANALYZE_STEPS[min(step, len(ANALYZE_STEPS) - 1)],
                     steps=ANALYZE_STEPS)

    def result(self, res: dict) -> None:
        self.publish("result", score=res.get("score"), correct=res.get("correct"), status=res.get("status"),
                     feedback=res.get("feedback"), subscores=res.get("subscores"), crop_url=res.get("crop_url"))

    def rearm(self) -> None:
        """After a result, new ink on the same character (a retry) starts a fresh attempt."""
        self.final_started = False
        self.request = None


AUTO = AutoGrader()
