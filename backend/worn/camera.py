"""Low-latency camera relay: the glasses push JPEG preview frames, viewers get the newest one.

Only the latest frame is kept (no queue anywhere): a slow viewer simply skips frames. Publishers:
WS /ws/camera (binary JPEG messages, optionally preceded by a JSON text message {ts, seq, w, h}, or
{ts, jpeg: base64}) or POST /camera/frame. Viewers: WS /ws/camera (text meta then binary per frame),
GET /camera.mjpg, GET /camera.jpg. Listeners (the auto-grader) get a callback per new frame.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections import deque
from typing import Awaitable, Callable

BOUNDARY = "wornframe"


class Relay:
    def __init__(self) -> None:
        self.jpeg: bytes | None = None
        self.meta: dict = {}
        self.seq = 0
        self._cond: asyncio.Condition | None = None
        self._times: deque = deque(maxlen=30)
        self.viewers = 0
        self.publishers = 0
        self.listeners: list[Callable[[bytes, dict], Awaitable[None] | None]] = []

    def cond(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    async def publish(self, jpeg: bytes, meta: dict | None = None) -> dict:
        if not jpeg or jpeg[:2] != b"\xff\xd8":
            raise ValueError("not a JPEG")
        now = time.time()
        meta = dict(meta or {})
        ts = meta.get("ts")
        if isinstance(ts, (int, float)) and ts > 1e12:
            ts = ts / 1000  # ms epoch
        meta["ts"] = float(ts) if isinstance(ts, (int, float)) else now
        meta["recv_ts"] = now
        async with self.cond():
            self.seq += 1
            meta["seq"] = self.seq
            self.jpeg, self.meta = jpeg, meta
            self._times.append(now)
            self.cond().notify_all()
        for fn in list(self.listeners):
            try:
                r = fn(jpeg, meta)
                if asyncio.iscoroutine(r):
                    asyncio.create_task(r)
            except Exception:
                pass
        return meta

    async def wait_newer(self, seq: int, timeout: float = 2.0) -> tuple[int, bytes | None, dict]:
        """Block until a frame newer than `seq` exists (or timeout) → (seq, jpeg, meta). Always the newest."""
        async with self.cond():
            if self.seq <= seq:
                try:
                    await asyncio.wait_for(self.cond().wait_for(lambda: self.seq > seq), timeout)
                except asyncio.TimeoutError:
                    pass
            return self.seq, self.jpeg, dict(self.meta)

    def status(self) -> dict:
        now = time.time()
        recent = [t for t in self._times if now - t < 3]
        fps = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 1 and recent[-1] > recent[0] else 0.0
        return {"seq": self.seq, "fps": round(fps, 1), "age_s": round(now - self.meta["recv_ts"], 2) if self.meta else None,
                "latency_ms": round((self.meta["recv_ts"] - self.meta["ts"]) * 1000) if self.meta else None,
                "size": len(self.jpeg) if self.jpeg else 0, "viewers": self.viewers, "publishers": self.publishers,
                "w": self.meta.get("w"), "h": self.meta.get("h")}


RELAY = Relay()


def decode_b64(s: str) -> bytes:
    if s.startswith("data:"):
        s = s.split(",", 1)[1]
    return base64.b64decode(s)


async def mjpeg(min_interval: float = 0.0):
    seq = 0
    RELAY.viewers += 1
    try:
        while True:
            seq, jpeg, _meta = await RELAY.wait_newer(seq, timeout=2.0)
            if jpeg is None:
                continue
            yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n").encode() + jpeg + b"\r\n"
            if min_interval:
                await asyncio.sleep(min_interval)
    finally:
        RELAY.viewers -= 1
