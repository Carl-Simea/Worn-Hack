"""Real-world tests on teammates' notebook photos (test_data/handwriting): pen on lined paper,
real light, shadows and angles, 3 writers. Thresholds sit a little under the measured numbers in
test_data/eval_results.md so a regression fails loudly. Tier 3 needs Ollama: `pytest -m live`."""

from __future__ import annotations

import asyncio

import pytest

import eval_handwriting as E


@pytest.fixture(scope="module")
def t1():
    return E.tier1()


@pytest.fixture(scope="module")
def t2():
    return E.tier2()


def test_ink_extraction_ignores_lines_holes_spiral_shadows():
    res = E.ink_precision()
    for page in res["pages"]:
        assert page["ink_px"] > 1500, page  # the writing is found
        assert page["in_writing_band"] >= 0.85, page  # almost nothing outside it


def test_tier1_no_false_new_strokes(t1):
    """Notebook lines, shadows, dimming, recompression and camera wobble never count as a stroke."""
    assert t1["false_new_stroke"] == 0, [c for c in t1["cases"] if not c["expected"] and c["got"]]


def test_tier1_detects_a_real_stroke_even_when_camera_moved(t1):
    assert t1["missed_strokes"] == 0


def test_tier1_is_fast(t1):
    assert t1["latency"]["max_ms"] < 300


def test_tier2_tolerates_handwriting_styles(t2):
    for style, v in t2["by_style"].items():
        assert v["done_rate"] >= 0.8, (style, v)  # print, cursive-ish, marker, mixed


def test_tier2_prefers_right_char_over_confusable(t2):
    assert t2["separation"] >= 0.8


def test_tier2_under_300ms(t2):
    assert t2["latency"]["max_ms"] < 300


@pytest.mark.live
def test_tier3_vision_on_real_handwriting():
    """qwen2.5vl reads tilted, shadowed real photos and never phrases feedback harshly."""
    res = asyncio.run(E.tier3())
    kinds = res["by_kind"]
    assert kinds["real: as photographed"]["accuracy"] >= 0.8, kinds
    assert kinds["real: tilted 8° + shadow"]["accuracy"] >= 0.7, kinds
    assert kinds["real: wrong target (must reject)"]["accuracy"] >= 0.8, kinds
    assert res["harsh_feedback"] == 0
    assert res["latency"]["avg_ms"] < 5000
