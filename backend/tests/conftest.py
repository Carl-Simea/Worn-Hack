"""Test setup: isolated data/capture dirs, a small fixed content set (so tests don't depend on
content/ being mid-edit), and no model warm-up. Tests marked `live` need Ollama running:
    uv run pytest                 # fast suite, models mocked
    uv run pytest -m live         # real qwen2.5vl / qwen2.5 calls on the real-world photos
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
TEST_DATA = BACKEND / "test_data"

_tmp = Path(tempfile.mkdtemp(prefix="worn-tests-"))
CONTENT = _tmp / "content"
(CONTENT / "strokes" / "mandarin").mkdir(parents=True)
for cp in ("4f60", "597d", "6c34", "4e00"):  # 你 好 水 一 (hanzi-writer data from content/)
    src = ROOT / "content" / "strokes" / "mandarin" / f"{cp}.json"
    if src.exists():
        shutil.copy(src, CONTENT / "strokes" / "mandarin" / src.name)

LESSONS = {
    "mandarin": {"lang": "mandarin", "name": "Mandarin Chinese", "rtl": False, "items": [
        {"id": "hello", "text": "你好", "chars": ["你", "好"], "romanization": "nǐ hǎo", "meaning": "hello"},
        {"id": "water", "text": "水", "chars": ["水"], "romanization": "shuǐ", "meaning": "water"},
        {"id": "one", "text": "一", "chars": ["一"], "romanization": "yī", "meaning": "one"}]},
    "hebrew": {"lang": "hebrew", "name": "Hebrew", "rtl": True, "phrases": [  # old key on purpose
        {"id": "hello", "text": "שלום", "chars": ["ש", "ל", "ו", "ם"], "romanization": "shalom", "meaning": "hello"},
        {"id": "one", "text": "אחד", "chars": ["א", "ח", "ד"], "romanization": "echad", "meaning": "one"}]},
    "greek": {"lang": "greek", "name": "Greek", "rtl": False, "items": [
        {"id": "water", "text": "νερό", "chars": ["ν", "ε", "ρ", "ό"], "romanization": "neró", "meaning": "water"}]},
    "japanese": {"lang": "japanese", "name": "Japanese", "items": [  # cut language: must be hidden
        {"id": "hello", "text": "こ", "chars": ["こ"]}]},
}
for lang, data in LESSONS.items():
    (CONTENT / f"{lang}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

os.environ.update({
    "WORN_CONTENT_DIR": str(CONTENT),
    "WORN_DATA_DIR": str(_tmp / "data"),
    "WORN_CAPTURE_DIR": str(_tmp / "captures"),
    "WORN_WARM": "0",
})
sys.path.insert(0, str(BACKEND))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

FONT = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs a running Ollama with the Worn models")


def pytest_collection_modifyitems(config, items):
    if config.getoption("-m") and "live" in config.getoption("-m"):
        return
    skip = pytest.mark.skip(reason="live model test: run with -m live")
    for it in items:
        if "live" in it.keywords:
            it.add_marker(skip)


def paper_crop(writer: int = 1) -> Image.Image:
    """A blank patch of a teammate's real notebook page (ruled lines, real light), 640x480."""
    im = Image.open(TEST_DATA / "handwriting" / f"writer{writer}.jpg").convert("RGB")
    w, h = im.size
    box = (int(0.30 * w), int(0.45 * h), int(0.30 * w) + int(0.55 * w), int(0.45 * h) + int(0.55 * w * 0.75))
    return im.crop(box).resize((640, 480))


def write_on_paper(char: str, writer: int = 1, *, size: int = 230, slant: float = 0.0, stroke: int = 0,
                   tilt: float = 0.0, shadow: float = 0.0, ink=(28, 30, 48), quality: int = 88) -> bytes:
    """Render char like pen on real paper: optional slant (cursive-ish), heavier stroke (marker),
    camera tilt and a shadow gradient. Returns JPEG bytes."""
    paper = paper_crop(writer)
    layer = Image.new("L", paper.size, 0)
    ImageDraw.Draw(layer).text((320, 235), char, font=ImageFont.truetype(FONT, size), fill=255, anchor="mm",
                               stroke_width=stroke, stroke_fill=255)
    if slant:
        layer = layer.transform(layer.size, Image.Transform.AFFINE, (1, slant, -slant * 240, 0, 1, 0),
                                resample=Image.Resampling.BICUBIC)
    ink_img = Image.new("RGB", paper.size, ink)
    paper.paste(ink_img, mask=layer)
    if tilt:
        paper = paper.rotate(tilt, resample=Image.Resampling.BICUBIC, fillcolor=(120, 110, 100))
    if shadow:
        import numpy as np
        a = np.asarray(paper).astype("float32")
        g = np.linspace(1 - shadow, 1, a.shape[1], dtype="float32")[None, :, None]
        paper = Image.fromarray((a * g).clip(0, 255).astype("uint8"))
    out = io.BytesIO()
    paper.save(out, "JPEG", quality=quality)
    return out.getvalue()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app as app_mod
    from worn import memory
    from worn.live import LIVE
    LIVE.reset()
    memory.reset()
    with TestClient(app_mod.app) as c:
        yield c
