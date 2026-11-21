"""Live mirror of the glasses display over USB: `adb exec-out screencap -p` as MJPEG (added by agent B for /live).

One shared grabber serves every viewer: frames younger than MIN_AGE are reused, so two open /live tabs don't double
the adb load. If adb is slow we simply take the next frame when it arrives (no queue, so no lag builds up). If adb is
missing or the glasses are unplugged, the stream keeps running with a "not connected" frame and retries every second.

Env: WORN_ADB (path to adb, default "adb"), WORN_ADB_SERIAL (pick one device when several are attached).
"""

from __future__ import annotations

import asyncio
import io
import os
import shutil
import time

from PIL import Image, ImageDraw, ImageFont

ADB = os.environ.get("WORN_ADB") or shutil.which("adb") or "/opt/homebrew/bin/adb"
SERIAL = os.environ.get("WORN_ADB_SERIAL", "")
FPS = 5.0
MIN_AGE = 0.15      # reuse a frame this fresh for other viewers
TIMEOUT = 3.0       # a screencap that takes longer counts as "unplugged"
BOUNDARY = "wornframe"

_lock = asyncio.Lock()
_last: dict = {"jpeg": None, "ts": 0.0, "ok": False, "error": "not started", "ms": None, "size": None}
_placeholder: bytes | None = None


def _cmd() -> list[str]:
    return [ADB] + (["-s", SERIAL] if SERIAL else []) + ["exec-out", "screencap", "-p"]


def _to_jpeg(png: bytes) -> tuple[bytes, tuple[int, int]]:
    im = Image.open(io.BytesIO(png)).convert("RGB")
    out = io.BytesIO()
    im.save(out, "JPEG", quality=80)
    return out.getvalue(), im.size


def placeholder() -> bytes:
    global _placeholder
    if _placeholder is None:
        im = Image.new("RGB", (640, 480), (0, 0, 0))
        d = ImageDraw.Draw(im)
        try:
            f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
        except OSError:
            f = ImageFont.load_default()
        t = "Glasses not connected"
        b = d.textbbox((0, 0), t, font=f)
        d.text((320 - (b[0] + b[2]) / 2, 240 - (b[1] + b[3]) / 2), t, font=f, fill=(110, 114, 128))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=80)
        _placeholder = out.getvalue()
    return _placeholder


async def grab() -> dict:
    """Return the freshest frame state ({jpeg, ts, ok, error, ms, size}), capturing only if the cache is stale."""
    async with _lock:
        if time.time() - _last["ts"] < MIN_AGE:
            return _last
        t0 = time.perf_counter()
        try:
            p = await asyncio.create_subprocess_exec(*_cmd(), stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.PIPE)
            try:
                png, err = await asyncio.wait_for(p.communicate(), TIMEOUT)
            except asyncio.TimeoutError:
                p.kill()
                await p.wait()
                raise RuntimeError("adb timed out")
            if p.returncode != 0 or not png.startswith(b"\x89PNG"):
                raise RuntimeError((err or png[:120]).decode(errors="replace").strip() or f"adb exit {p.returncode}")
            jpeg, size = await asyncio.to_thread(_to_jpeg, png)
            _last.update(jpeg=jpeg, ok=True, error=None, size=size, ms=round((time.perf_counter() - t0) * 1000))
        except (OSError, RuntimeError, ValueError) as e:
            _last.update(jpeg=None, ok=False, error=str(e)[:160], ms=None)
        _last["ts"] = time.time()
        return _last


async def mjpeg():
    """multipart/x-mixed-replace body: ~FPS frames a second while plugged in, a placeholder once a second otherwise."""
    while True:
        t0 = time.perf_counter()
        st = await grab()
        jpeg = st["jpeg"] if st["ok"] else placeholder()
        yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n").encode() + jpeg + b"\r\n"
        wait = (1 / FPS) if st["ok"] else 1.0
        await asyncio.sleep(max(0.0, wait - (time.perf_counter() - t0)))


def status() -> dict:
    return {"connected": bool(_last["ok"]), "error": _last["error"], "capture_ms": _last["ms"],
            "size": _last["size"], "age_s": round(time.time() - _last["ts"], 2) if _last["ts"] else None,
            "fps": FPS, "adb": ADB, "serial": SERIAL or None}
