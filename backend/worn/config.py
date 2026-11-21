"""Paths, model names and timeouts. Every value can be overridden with a WORN_* env var."""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # backend/
ROOT = HERE.parent
CONTENT_DIR = Path(os.environ.get("WORN_CONTENT_DIR", ROOT / "content"))
WEB_DIR = Path(os.environ.get("WORN_WEB_DIR", ROOT / "web"))
SEED_DIR = HERE / "seed"
DATA_DIR = Path(os.environ.get("WORN_DATA_DIR", HERE / "data"))  # memory + journal (gitignored)
CAPTURE_DIR = Path(os.environ.get("WORN_CAPTURE_DIR", HERE / "captures"))

OLLAMA_URL = os.environ.get("WORN_OLLAMA_URL", "http://127.0.0.1:11434")
VISION_MODEL = os.environ.get("WORN_VISION_MODEL", "qwen2.5vl:7b")
TUTOR_MODEL = os.environ.get("WORN_TUTOR_MODEL", "qwen2.5:14b")
TUTOR_FALLBACK = os.environ.get("WORN_TUTOR_FALLBACK", "qwen2.5:7b")
KEEP_ALIVE = os.environ.get("WORN_KEEP_ALIVE", "12h")
TUTOR_CTX = int(os.environ.get("WORN_TUTOR_CTX", "2048"))
VISION_CTX = int(os.environ.get("WORN_VISION_CTX", "4096"))

GRADE_TIMEOUT = float(os.environ.get("WORN_GRADE_TIMEOUT", "30"))
TUTOR_BUDGET = float(os.environ.get("WORN_TUTOR_BUDGET", "3"))  # brief: fall back to 7b past 3 s
HEDGE_AFTER = float(os.environ.get("WORN_HEDGE_AFTER", "1.0"))  # start 7b in parallel after this
DECIDE_CAP = float(os.environ.get("WORN_DECIDE_CAP", "4.5"))  # total; past it the rule policy decides
FALLBACK_TIMEOUT = float(os.environ.get("WORN_FALLBACK_TIMEOUT", "6"))
WARM_MODELS = os.environ.get("WORN_WARM", "1") == "1"
FAKE_GRADE = os.environ.get("WORN_FAKE_GRADE") == "1"  # demo safety net: canned pass if vision is down

LANG_ORDER = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]
CUT_LANGS = {"asl", "japanese"}  # ASL cut 2026-11-20, Japanese cut 2026-11-21

# Language + script names only (brief: never flags).
LANGS = {
    "mandarin": {"name": "Mandarin Chinese", "script": "Simplified Chinese characters", "rtl": False},
    "hindi": {"name": "Hindi", "script": "Devanagari", "rtl": False},
    "arabic": {"name": "Arabic", "script": "Arabic script (isolated letters)", "rtl": True},
    "russian": {"name": "Russian", "script": "Cyrillic (printed)", "rtl": False},
    "hebrew": {"name": "Hebrew", "script": "Hebrew alphabet (block print)", "rtl": True},
    "greek": {"name": "Greek", "script": "Greek alphabet", "rtl": False},
}

for d in (DATA_DIR, CAPTURE_DIR):
    d.mkdir(parents=True, exist_ok=True)
