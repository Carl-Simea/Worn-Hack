"""Everything GET /live/state shows: session, glasses, latest photo, last result, the agent's
steps, the event log, per-tier latency, progress and listening. Process memory only."""

from __future__ import annotations

import itertools
import statistics
import threading
import time
from collections import deque
from typing import Any

_lock = threading.RLock()
_ids = itertools.count(1)

MAX_EVENTS = 60
MAX_STEPS = 80


class Live:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        with _lock:
            self.version = 0
            self.session: dict | None = None
            self.result: dict | None = None
            self.next: dict | None = None
            self.glasses: dict[str, Any] = {"connected": False, "showing": "idle", "phase": "idle",
                                            "stroke": 0, "stroke_count": 0, "last_seen": None}
            self.latest_photo_url: str | None = None
            self.listening = False
            self.events: deque = deque(maxlen=MAX_EVENTS)
            self.steps: deque = deque(maxlen=MAX_STEPS)
            self.lat: dict[str, deque] = {t: deque(maxlen=50) for t in ("tier1", "tier2", "tier3")}
            self.tries = 0  # consecutive misses on the current char

    def bump(self) -> int:
        with _lock:
            self.version += 1
            return self.version

    # -------------------------------------------------------------- writers

    def set_session(self, s: dict) -> dict:
        with _lock:
            same_char = self.session and (self.session.get("lang"), self.session.get("char")) == (s.get("lang"), s.get("char"))
            if not same_char:
                self.tries = 0
            self.session = s
            self.result = None
            self.next = None
            self.glasses.update({"showing": "stroke_animation" if s.get("show_char", True) else "audio_prompt",
                                 "phase": "watch", "stroke": 0, "stroke_count": s.get("stroke_count", 0)})
            s["version"] = self.bump()
            self.add_event("session", {k: s.get(k) for k in ("lang", "item_id", "char", "char_index", "mode")}, bump=False)
            return s

    def set_result(self, r: dict, nxt: dict | None = None) -> None:
        with _lock:
            self.result = r
            self.next = nxt
            self.tries = 0 if r.get("correct") else self.tries + 1
            self.glasses.update({"showing": "result", "phase": "result"})
            if r.get("image_url"):
                self.latest_photo_url = r["image_url"]
            self.bump()

    def set_photo(self, url: str) -> None:
        with _lock:
            self.latest_photo_url = url
            self.bump()

    def set_stroke(self, stroke: int, stroke_count: int) -> None:
        with _lock:
            self.glasses.update({"stroke": stroke, "stroke_count": stroke_count, "phase": "write"})
            if self.session is not None:
                self.session["stroke_index"] = stroke
            self.bump()

    def latency(self, tier: str, ms: float) -> None:
        with _lock:
            if tier in self.lat:
                self.lat[tier].append(float(ms))
                self.bump()

    def add_event(self, type_: str, data: Any = None, bump: bool = True) -> dict:
        with _lock:
            e = {"id": next(_ids), "ts": time.time(), "type": type_, "data": data}
            self.events.append(e)
            if bump:
                self.bump()
            return e

    def add_step(self, run_id: str, phase: str, summary: str, *, tool: str | None = None, ms: float | None = None,
                 data: Any = None, model: str | None = None, status: str = "ok") -> dict:
        """phase: observe | evaluate | decide | act. tool: the tool called, if any."""
        with _lock:
            s = {"id": next(_ids), "run_id": run_id, "ts": time.time(), "phase": phase, "tool": tool,
                 "summary": summary, "ms": None if ms is None else int(ms), "model": model,
                 "status": status, "data": data}
            self.steps.append(s)
            self.bump()
            return s

    # -------------------------------------------------------------- events from clients

    def apply_event(self, type_: str, data: dict | None) -> dict:
        """POST /event. Known types update state; every event lands in the log."""
        data = data or {}
        with _lock:
            g = self.glasses
            if type_ in ("glasses", "glasses_state"):
                for k in ("connected", "showing", "phase", "stroke", "stroke_count"):
                    if k in data:
                        g[k] = data[k]
                g["last_seen"] = time.time()
            elif type_ == "glasses_connected":
                g.update({"connected": True, "last_seen": time.time()})
            elif type_ == "glasses_disconnected":
                g["connected"] = False
            elif type_ == "showing":
                g["showing"] = data.get("what", data.get("showing", g["showing"]))
            elif type_ == "phase":
                g["phase"] = data.get("phase", g["phase"])
            elif type_ == "stroke":
                self.set_stroke(int(data.get("stroke", g["stroke"])), int(data.get("stroke_count", g["stroke_count"])))
            elif type_ == "tier1":
                if "ms" in data:
                    self.lat["tier1"].append(float(data["ms"]))
            elif type_ in ("listening", "listening_start", "listening_stop"):
                self.listening = (type_ == "listening_start") or (type_ == "listening" and bool(data.get("on", True)))
            elif type_ == "photo" and data.get("url"):
                self.latest_photo_url = data["url"]
            return self.add_event(type_, data)

    # -------------------------------------------------------------- reader

    def _lat(self, tier: str) -> dict:
        v = list(self.lat[tier])
        if not v:
            return {"last_ms": None, "avg_ms": None, "p95_ms": None, "n": 0}
        s = sorted(v)
        return {"last_ms": int(v[-1]), "avg_ms": int(statistics.mean(v)),
                "p95_ms": int(s[min(len(s) - 1, int(0.95 * len(s)))]), "n": len(v)}

    def snapshot(self, progress: dict | None = None, steps: int = 40, events: int = 30) -> dict:
        with _lock:
            g = dict(self.glasses)
            if g.get("last_seen") and time.time() - g["last_seen"] > 30 and g.get("connected"):
                g["stale"] = True
            return {
                "version": self.version,
                "ts": time.time(),
                "session": self.session,
                "glasses": g,
                "latest_photo_url": self.latest_photo_url,
                "last_result": self.result,
                "next": self.next,
                "agent_steps": list(self.steps)[-steps:],
                "events": list(self.events)[-events:],
                "latency": {t: self._lat(t) for t in ("tier1", "tier2", "tier3")},
                "progress": progress or {},
                "listening": self.listening,
                "tries": self.tries,
            }


LIVE = Live()
