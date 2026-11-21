"""Scribi's voice: text → 16 kHz mono WAV, cached by (engine, voice, text).

Engines: piper (local neural TTS: WORN_TTS=piper, binary + voice in data/tts/) when available, else macOS
`say` with a friendly voice (WORN_SAY_VOICE, default Samantha). The glasses fall back to device TTS when
no audio_url comes back.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from pathlib import Path

from . import config

TTS_DIR = config.DATA_DIR / "tts"
CACHE = config.DATA_DIR / "say"
ENGINE = os.environ.get("WORN_TTS", "auto")  # auto | piper | say
SAY_VOICE = os.environ.get("WORN_SAY_VOICE", "Samantha")
SAY_RATE = os.environ.get("WORN_SAY_RATE", "195")
PIPER_VOICE = os.environ.get("WORN_PIPER_VOICE", "en_US-amy-medium")
_lock = threading.Lock()
_piper_ok: bool | None = None


def _piper_paths() -> tuple[Path, Path]:
    return TTS_DIR / "piper" / "piper", TTS_DIR / f"{PIPER_VOICE}.onnx"


def piper_available() -> bool:
    """Only when explicitly enabled (WORN_TTS=piper): the binary is a download the user has to approve."""
    global _piper_ok
    if ENGINE != "piper":
        return False
    if _piper_ok is None:
        exe, model = _piper_paths()
        _piper_ok = exe.exists() and model.exists() and model.stat().st_size > 1_000_000
    return _piper_ok


def engine() -> dict:
    return {"engine": "piper" if piper_available() else "say",
            "voice": PIPER_VOICE if piper_available() else SAY_VOICE}


def clean(text: str) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()[:400]
    return re.sub(r"[*_#`]", "", t)


def synth(text: str) -> Path:
    """→ cached WAV path. Raises ValueError on empty text, RuntimeError if no engine works."""
    global _piper_ok
    text = clean(text)
    if not text:
        raise ValueError("nothing to say")
    eng = engine()
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{eng['engine']}|{eng['voice']}|{SAY_RATE}|{text}".encode()).hexdigest()[:16]
    out = CACHE / f"{key}.wav"
    if out.exists() and out.stat().st_size > 100:
        return out
    with _lock:
        if out.exists() and out.stat().st_size > 100:
            return out
        tmp = out.with_suffix(".tmp.wav")
        if eng["engine"] == "piper":
            exe, model = _piper_paths()
            try:
                subprocess.run([str(exe), "--model", str(model), "--output_file", str(tmp)], input=text.encode(),
                               check=True, timeout=20, capture_output=True,
                               env={**os.environ, "DYLD_LIBRARY_PATH": str(exe.parent)})
                tmp.replace(out)
                return out
            except Exception:
                _piper_ok = False  # fall through to `say`
        subprocess.run(["say", "-v", SAY_VOICE, "-r", SAY_RATE, "-o", str(tmp), "--file-format=WAVE",
                        "--data-format=LEI16@16000", "--channels=1", "--", text], check=True, timeout=20,
                       capture_output=True)
        tmp.replace(out)
    return out


def url_for(path: Path) -> str:
    return f"/tts/{path.name}"
