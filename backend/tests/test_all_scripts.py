"""Every script end to end: session → stroke template from content/strokes/{lang} → grade a rendered correct
glyph (>= 70) and a wrong one (< 40) → voice "learn X", English word names, "how do I write X in Y".
Models mocked (the fake rubric reads what fake.seen says)."""

from __future__ import annotations

import pytest

from conftest import write_on_paper
from test_routes import fake  # noqa: F401
from test_voice import FakeNLU, nlu, say, vc  # noqa: F401
from worn import measure, strokes

# lang, item, char_index, target, wrong (same script)
CASES = [
    ("mandarin", "water", 0, "水", "你"),
    ("hindi", "hello", 0, "न", "क"),
    ("arabic", "hello", 0, "م", "ر"),
    ("russian", "hello", 0, "П", "Д"),
    ("hebrew", "hello", 0, "ש", "ל"),
    ("greek", "water", 0, "ν", "λ"),
]


def _start(client, lang, item, ci):
    r = client.post("/session", json={"lang": lang, "item_id": item, "char_index": ci})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("lang,item,ci,target,wrong", CASES, ids=[c[0] for c in CASES])
def test_session_and_stroke_template_from_content(client, lang, item, ci, target, wrong):
    s = _start(client, lang, item, ci)
    assert s["char"].casefold() == target.casefold() and s["stroke_count"] >= 1
    assert client.get(s["stroke_url"]).status_code == 200
    tm = strokes.template(lang, s["char"])
    if lang != "mandarin":
        assert "suggested" in tm["source"] or tm["source"].endswith(".svg"), tm["source"]  # C's paths, not the font
    m = client.post("/stroke-match", files={"image": ("p.jpg", write_on_paper(s["char"]), "image/jpeg")},
                    data={"char": s["char"], "stroke_index": str(s["stroke_count"] - 1), "lang": lang}).json()
    assert m["ink"] and m["score"] > 0


@pytest.mark.parametrize("lang,item,ci,target,wrong", CASES, ids=[c[0] for c in CASES])
def test_reference_is_the_matching_noto_font(lang, item, ci, target, wrong):
    want = {"mandarin": "NotoSansSC", "hindi": "NotoSansDevanagari", "arabic": "NotoNaskhArabic",
            "hebrew": "NotoSansHebrew", "russian": "NotoSans-", "greek": "NotoSans-"}[lang]
    assert measure.font_name(lang).startswith(want.rstrip("-"))
    assert measure.glyph_mask(lang, target) is not None


@pytest.mark.parametrize("lang,item,ci,target,wrong", CASES, ids=[c[0] for c in CASES])
def test_grade_correct_glyph_passes_and_wrong_glyph_fails(client, fake, lang, item, ci, target, wrong):
    s = _start(client, lang, item, ci)
    char = s["char"]
    good = client.post("/grade", files={"image": ("p.jpg", write_on_paper(char), "image/jpeg")}).json()
    assert good["status"] == "ok" and good["score"] >= 70 and good["correct"], (lang, good["score"], good["shape"])
    fake.seen = wrong
    bad = client.post("/grade", files={"image": ("p.jpg", write_on_paper(wrong), "image/jpeg")}).json()
    assert bad["status"] == "ok" and bad["score"] < 40 and not bad["correct"], (lang, bad["score"], bad["shape"])


NAMES = {"mandarin": "Mandarin", "hindi": "Hindi", "arabic": "Arabic", "russian": "Russian", "hebrew": "Hebrew",
         "greek": "Greek"}


@pytest.mark.parametrize("lang", list(NAMES))
def test_voice_learn_word_and_how_do_i_write(vc, nlu, lang):
    d = say(vc, f"learn {NAMES[lang]}", "home")
    assert d["intent"] == "learn" and d["nav"] == {"screen": "words", "lang": lang}
    items = {i["id"]: i for i in vc.get("/content").json()["langs"][[l["lang"] for l in vc.get("/content").json()["langs"]].index(lang)]["items"]}
    word = "water" if "water" in items else "hello"
    d = say(vc, word, "words")
    assert d["intent"] == "select" and d["session"]["lang"] == lang and d["session"]["item_id"] == word
    vc.post("/reset")
    d = say(vc, f"how do I write {word} in {NAMES[lang]}", "home")
    assert d["intent"] == "select" and d["session"]["lang"] == lang and d["session"]["item_id"] == word


@pytest.mark.parametrize("lang,item,ci,target,wrong", CASES, ids=[c[0] for c in CASES])
def test_glasses_lesson_restores_the_session_after_a_restart(client, fake, lang, item, ci, target, wrong):
    client.post("/reset")  # backend lost its session (restart)
    client.post("/app-state", json={"screen": "lesson", "lang": lang, "item_id": item, "char_index": ci,
                                    "phase": "your_turn"})
    s = client.get("/session").json()
    assert (s["lang"], s["item_id"], s["char_index"]) == (lang, item, ci)
    g = client.post("/grade", files={"image": ("p.jpg", write_on_paper(s["char"]), "image/jpeg")})
    assert g.status_code == 200 and g.json()["status"] == "ok"
