"""Pure-function tests: scripts, grading parser, guardrails, stroke templates."""

from __future__ import annotations

from worn import agent, scripts, strokes, vision


def test_split_units_per_language():
    assert scripts.split_units("你好", "mandarin") == ["你", "好"]
    assert scripts.split_units("नमस्ते", "hindi") == ["न", "म", "स्ते"]  # aksharas
    assert scripts.split_units("شُكْرًا", "arabic") == ["ش", "ك", "ر", "ا"]  # harakat dropped
    assert scripts.split_units("שָׁלוֹם", "hebrew") == ["ש", "ל", "ו", "ם"]  # niqqud dropped
    assert scripts.split_units("νερό", "greek") == ["ν", "ε", "ρ", "ό"]  # accent kept
    assert scripts.split_units("Привет!", "russian") == ["П", "р", "и", "в", "е", "т"]


def test_in_script():
    assert scripts.in_script("γεια σου", "greek") and not scripts.in_script("γεια you", "greek")
    assert scripts.in_script("תודה", "hebrew") and not scripts.in_script("тода", "hebrew")
    assert not scripts.in_script("水请 water", "mandarin")


def test_parse_grade():
    assert vision.parse_grade({"seen": "你", "score": 91}, "你")["correct"] is True
    g = vision.parse_grade({"seen": "好", "score": 88}, "你")
    assert g["correct"] is False and g["score"] <= 45 and "好" in g["feedback"]
    blank = vision.parse_grade({"seen": "", "score": 30, "fix": "make it straighter"}, "你")
    assert blank["score"] == 0 and "can't see" in blank["feedback"]
    # the 2026-11-20 bug: model left "seen" empty but named the char in its fix
    assert vision.parse_grade({"seen": "", "score": 70, "fix": "looks like '你' but tilted"}, "你")["seen"] == "你"


def test_guardrails():
    dec = {"thought": "", "action": "advance", "mood": "", "reaction": "x"}
    assert agent.guardrails(dec, correct=False, tries_after=1)[0]["action"] == "retry"
    assert agent.guardrails(dec, correct=False, tries_after=3)[0]["action"] == "advance"
    assert agent.guardrails({**dec, "action": "retry"}, correct=True, tries_after=0)[0]["action"] == "advance"


def test_kind_filters_harsh_words():
    assert agent.kind("That's sloppy.", "fallback") == "fallback"
    assert agent.kind("Add the dot on top.", "fallback") == "Add the dot on top."


def test_templates_self_match():
    """Strokes drawn from a template must match that template; stroke counts must be sane."""
    import cv2
    import numpy as np
    for lang, ch, n in [("mandarin", "你", 7), ("mandarin", "一", 1)]:
        tm = strokes.template(lang, ch)
        assert len(tm["strokes"]) == n
        img = np.full((480, 640, 3), (216, 231, 236), np.uint8)
        for s in tm["strokes"]:
            cv2.polylines(img, [(s * 380 + [130, 50]).astype(np.int32)], False, (40, 25, 25), 9)
        raw = cv2.imencode(".jpg", img)[1].tobytes()
        assert strokes.match_stroke(raw, lang, ch, n - 1)["char_done"]


def test_font_fallback_templates_for_every_script():
    for lang, ch in [("hindi", "न"), ("arabic", "م"), ("russian", "П"), ("hebrew", "ש"), ("greek", "λ")]:
        tm = strokes.template(lang, ch)
        assert len(tm["strokes"]) >= 1 and len(tm["strokes"][0]) > 20


def test_svg_path_parser():
    pts = strokes.parse_svg_path("M10,10c0,10 10,10 10,0L30,30z")
    assert len(pts) > 10 and abs(pts[-1][0] - 10) < 1e-3  # z returns to start


def test_grade_never_penalizes_form_or_style():
    # exact read with a low style score is still correct
    assert vision.parse_grade({"seen": "M", "score": 30}, "M", "latin")["correct"] is True
    # capital vs small letter counts, kindly
    g = vision.parse_grade({"seen": "п", "score": 80}, "П", "russian")
    assert g["correct"] and "Both count" in g["feedback"]
    # Greek accent missing: still correct, with the tip
    g = vision.parse_grade({"seen": "ο", "score": 80}, "ό", "greek")
    assert g["correct"] and "accent" in g["feedback"]
    # but a different letter is a miss, and Devanagari vowel signs are never stripped
    assert vision.parse_grade({"seen": "ע", "score": 60}, "ש", "hebrew")["correct"] is False
    assert vision.parse_grade({"seen": "न", "score": 90}, "ने", "hindi")["correct"] is False
    assert vision.parse_grade({"seen": "Б", "score": 90}, "В", "russian")["correct"] is False


def test_unicode_name_in_prompt():
    assert vision.unicode_name("ש") == "hebrew letter shin"
