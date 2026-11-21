"""Every route in the contract, with the models mocked (fast, deterministic)."""

from __future__ import annotations

import asyncio
import json

import pytest

from conftest import TEST_DATA, write_on_paper
from worn import agent, compose, llm, vision


class FakeModels:
    """vision: 'reads' whatever self.seen says. tutor: answers per prompt kind."""

    def __init__(self):
        self.seen = None  # None = read the target correctly
        self.vision_calls = 0
        self.tutor_calls = []

    async def vision_grade(self, jpeg, char, lang):
        self.vision_calls += 1
        seen = char if self.seen is None else self.seen
        data = {"seen": seen, "score": 92 if seen == char else 30, "fix": "" if seen == char else "Close the top loop."}
        return vision.parse_grade(data, char), {"model": "fake-vision", "ms": 5}

    async def tutor_json(self, prompt, *, system=None, validate=None, num_predict=256, temperature=0.3):
        self.tutor_calls.append(prompt)
        if "Translate this short message" in prompt:
            lang = next(l for l in ("Mandarin", "Hebrew", "Greek") if l in prompt)
            out = {"Mandarin": {"native": "谢谢朋友", "romanization": "xièxie péngyou"},
                   "Hebrew": {"native": "תודה חבר", "romanization": "toda chaver"},
                   "Greek": {"native": "ευχαριστώ φίλε", "romanization": "efcharistó fíle"}}[lang]
            data = {**out, "back_translation": "thank you friend", "suitable": "religion" not in prompt}
        elif "by its SOUND" in prompt:
            data = {"devanagari": "माया", "arabic": "مايا", "cyrillic": "Майя", "hebrew": "מאיה", "greek": "Μάγια"}
        else:  # decide
            correct = "correct=true" in prompt
            data = {"thought": "ok", "action": "advance" if correct else "advance",  # 'advance' on a miss tests guardrails
                    "mood": "celebrate" if correct else "encourage", "reaction": "You did it!" if correct else "Almost!"}
        return (validate(data) if validate else data), {"model": "fake-14b", "ms": 3, "fallback": False}


@pytest.fixture
def fake(monkeypatch):
    f = FakeModels()
    monkeypatch.setattr(vision, "grade", f.vision_grade)
    monkeypatch.setattr(llm, "tutor_json", f.tutor_json)
    return f


def start(client, lang="mandarin", item="hello", i=0, mode="write"):
    r = client.post("/session", json={"lang": lang, "item_id": item, "char_index": i, "mode": mode})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ health + content

def test_health(client):
    d = client.get("/health").json()
    assert d["ok"] is True
    assert d["langs"] == ["mandarin", "hebrew", "greek"]  # fixed order, japanese cut
    assert d["models"]["tutor"] == "qwen2.5:14b" and d["models"]["vision"] == "qwen2.5vl:7b"
    assert d["models"]["tutor_fallback"] == "qwen2.5:7b"


def test_content_normalizes_both_schemas(client):
    langs = {l["lang"]: l for l in client.get("/content").json()["langs"]}
    assert "japanese" not in langs
    he = langs["hebrew"]
    assert he["rtl"] is True and he["items"] == he["phrases"]  # old 'phrases' key -> both keys
    ni = langs["mandarin"]["items"][0]["char_info"][0]
    assert ni == {"char": "你", "stroke_count": 7, "stroke_url": "/static/content/strokes/mandarin/4f60.json"}


# ------------------------------------------------------------------ session

def test_session_write(client):
    s = start(client)
    for k in ("item_id", "char", "stroke_url", "audio_url", "stroke_count", "romanization", "meaning", "version"):
        assert k in s
    assert s["char"] == "你" and s["stroke_count"] == 7 and s["stroke_order"] == "true" and s["show_char"]
    assert client.get("/session").json()["char"] == "你"


def test_session_accepts_old_phrase_id(client):
    r = client.post("/session", json={"lang": "hebrew", "phrase_id": "hello", "char_index": 1})
    assert r.status_code == 200 and r.json()["char"] == "ל" and r.json()["rtl"] is True


def test_session_dictation_hides_char(client):
    s = start(client, "greek", "water", 3, "dictation")
    assert s["char"] == "ό" and s["show_char"] is False and "Listen" in s["prompt"]


def test_session_compose(client, fake):
    r = client.post("/session", json={"lang": "hebrew", "mode": "compose", "text": "thank you friend"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["item_id"].startswith("compose-") and s["chars"] if "chars" in s else True
    assert s["item"]["chars"] == ["ת", "ו", "ד", "ה", "ח", "ב", "ר"] and s["mode"] == "compose"
    nxt = client.post("/session", json={"lang": "hebrew", "item_id": s["item_id"], "char_index": 4}).json()
    assert nxt["char"] == "ח"


def test_session_errors_are_friendly(client):
    r = client.post("/session", json={"lang": "klingon", "item_id": "hello"})
    assert r.status_code == 404 and "message" in r.json()
    r = client.post("/session", json={"lang": "mandarin", "item_id": "hello", "char_index": 9})
    assert r.status_code == 400
    r = client.post("/session", json={"lang": "japanese", "item_id": "hello"})
    assert r.status_code == 404  # cut language
    r = client.post("/session", json={"lang": "mandarin", "item_id": "hello", "mode": "asl"})
    assert r.status_code == 422


def test_no_session_yet(client):
    assert client.get("/session").status_code == 404
    assert client.get("/session/result").status_code == 404


# ------------------------------------------------------------------ grade + agent

def test_grade_correct_runs_full_agent_loop(client, fake):
    start(client)
    r = client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")})
    assert r.status_code == 200, r.text
    g = r.json()
    for k in ("correct", "score", "feedback", "reaction"):
        assert k in g
    assert g["correct"] is True and g["reaction"] == "You did it!" and g["mood"] == "celebrate"
    assert g["next"]["char"] == "好" and g["next"]["action"] == "advance"
    assert g["image_url"].startswith("/captures/") and client.get(g["image_url"]).status_code == 200
    assert client.get("/session/result").json()["ts"] == g["ts"]
    steps = client.get("/live/state").json()["agent_steps"]
    run = [s for s in steps if s["run_id"] == g["agent"]["run_id"]]
    assert [s["phase"] for s in run][:1] == ["observe"]
    assert {"grade_character", "compare_to_template", "choose_next_item", "react"} <= {s["tool"] for s in run}
    assert any(s["phase"] == "decide" for s in run)
    assert all(s["ms"] is not None for s in run if s["tool"])


def test_grade_miss_guardrail_forces_retry_then_moves_on(client, fake):
    start(client)
    fake.seen = "好"
    img = write_on_paper("好")
    actions = []
    for _ in range(3):
        g = client.post("/grade", files={"image": ("p.jpg", img, "image/jpeg")}).json()
        actions.append(g["agent"]["action"])
        assert g["correct"] is False and g["score"] <= 45
    assert actions == ["retry", "retry", "advance"]  # the fake LLM always says advance; guardrail holds 2x
    steps = client.get("/live/state").json()["agent_steps"]
    assert any("guardrail" in s["summary"] for s in steps)


def test_grade_feedback_is_never_harsh(client, fake, monkeypatch):
    start(client)

    async def harsh(jpeg, char, lang):
        return {"correct": False, "score": 20, "seen": "x", "feedback": "That is messy and wrong."}, {"model": "f"}
    monkeypatch.setattr(vision, "grade", harsh)
    g = client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")}).json()
    assert "messy" not in g["feedback"].lower() and "wrong" not in g["feedback"].lower()


def test_grade_vision_down_is_friendly_503(client, monkeypatch):
    start(client)

    async def down(*a, **k):
        raise llm.LLMError("connection refused")
    monkeypatch.setattr(vision, "grade", down)
    r = client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")})
    assert r.status_code == 503 and "moment" in r.json()["message"]


def test_grade_rules_when_both_tutor_models_fail(client, fake, monkeypatch):
    start(client)

    async def fail(*a, **k):
        raise llm.LLMError("both down")
    monkeypatch.setattr(llm, "tutor_json", fail)
    g = client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")}).json()
    assert g["agent"]["decided_by"] == "rules" and g["reaction"]


def test_grade_rejects_non_image(client, fake):
    start(client)
    r = client.post("/grade", files={"image": ("p.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_session_next_applies_agent_choice(client, fake):
    start(client)
    assert client.post("/session/next").status_code == 409
    client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")})
    s = client.post("/session/next").json()
    assert s["char"] == "好" and s["char_index"] == 1


# ------------------------------------------------------------------ tier 2 / tier 1 routes

def test_stroke_match_route(client):
    start(client, "mandarin", "one")
    r = client.post("/stroke-match", files={"image": ("p.jpg", write_on_paper("一"), "image/jpeg")},
                    data={"char": "一", "stroke_index": 0})
    d = r.json()
    assert r.status_code == 200 and {"score", "done"} <= set(d)
    assert d["done"] is True and d["char_done"] is True and d["latency_ms"] < 300
    live = client.get("/live/state").json()
    assert live["latency"]["tier2"]["n"] == 1 and live["glasses"]["stroke_count"] == 1


def test_stroke_match_blank_paper(client):
    r = client.post("/stroke-match", files={"image": ("p.jpg", write_on_paper(" "), "image/jpeg")},
                    data={"char": "你", "stroke_index": 0, "lang": "mandarin"})
    assert r.json()["done"] is False and r.json()["ink"] is False


def test_ink_diff_route(client):
    before = write_on_paper(" ")
    after = write_on_paper("一")
    d = client.post("/ink-diff", files={"before": ("a.jpg", before, "image/jpeg"),
                                        "after": ("b.jpg", after, "image/jpeg")}).json()
    assert d["new_stroke"] is True
    same = client.post("/ink-diff", files={"before": ("a.jpg", before, "image/jpeg"),
                                           "after": ("b.jpg", before, "image/jpeg")}).json()
    assert same["new_stroke"] is False
    assert client.get("/live/state").json()["latency"]["tier1"]["n"] == 2


# ------------------------------------------------------------------ compose + name

def test_compose(client, fake):
    d = client.post("/compose", json={"text": "thank you friend", "lang": "greek"}).json()
    for k in ("native", "romanization", "back_translation", "chars", "note"):
        assert d[k]
    assert d["chars"] == ["ε", "υ", "χ", "α", "ρ", "ι", "σ", "τ", "ώ", "φ", "ί", "λ", "ε"][:len(d["chars"])]


def test_compose_rejects_unsuitable_and_long(client, fake):
    assert client.post("/compose", json={"text": "a religion message", "lang": "mandarin"}).status_code == 422
    assert client.post("/compose", json={"text": "x" * 200, "lang": "mandarin"}).status_code == 422
    assert client.post("/compose", json={"text": "hi", "lang": "klingon"}).status_code == 422


def test_name(client, fake):
    d = client.get("/name", params={"text": "Maya"}).json()
    assert set(d) >= {"devanagari", "arabic", "cyrillic", "hebrew", "greek", "note"}
    assert "katakana" not in d
    assert client.get("/name", params={"text": "Maya123"}).status_code == 422


# ------------------------------------------------------------------ events + live

def test_events_drive_live_state(client):
    for t, data in [("glasses_connected", {}), ("phase", {"phase": "write"}), ("showing", {"what": "stroke_animation"}),
                    ("stroke", {"stroke": 2, "stroke_count": 7}), ("tier1", {"ms": 42}), ("listening_start", {}),
                    ("speech", {"text": "ni hao"})]:
        assert client.post("/event", json={"type": t, "data": data}).json()["ok"]
    s = client.get("/live/state").json()
    for k in ("session", "glasses", "latest_photo_url", "last_result", "agent_steps", "events", "latency",
              "progress", "listening"):
        assert k in s
    g = s["glasses"]
    assert g["connected"] and g["phase"] == "write" and g["showing"] == "stroke_animation"
    assert g["stroke"] == 2 and g["stroke_count"] == 7
    assert s["listening"] is True and s["latency"]["tier1"]["last_ms"] == 42
    assert [e["type"] for e in s["events"]][-1] == "speech"
    client.post("/event", json={"type": "listening_stop"})
    assert client.get("/live/state").json()["listening"] is False


def test_live_state_since_is_cheap(client):
    v = client.get("/live/state").json()["version"]
    assert client.get("/live/state", params={"since": v}).json() == {"unchanged": True, "version": v}


def test_progress(client, fake):
    start(client)
    client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")})
    p = client.get("/live/state").json()["progress"]
    assert p["lang"] == "mandarin" and p["items_total"] == 3 and p["learned"] == 1 and p["chars_total"] == 2


# ------------------------------------------------------------------ journal + review

def test_journal_and_daily5(client, fake):
    assert client.get("/review").json()["count"] == 5  # empty memory: 5 new chars, never empty
    start(client)
    fake.seen = "好"
    client.post("/grade", files={"image": ("p.jpg", write_on_paper("好"), "image/jpeg")})
    fake.seen = None
    client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")})
    j = client.get("/journal", params={"lang": "mandarin"}).json()
    assert j["total"] == 2 and j["correct"] == 1 and j["entries"][0]["correct"] is True  # newest first
    assert j["chars"][0]["char"] == "你" and j["chars"][0]["attempts"] == 2
    assert client.get("/journal", params={"lang": "greek"}).json()["total"] == 0
    r = client.get("/review").json()
    assert r["title"] == "Daily 5" and r["items"][0]["char"] == "你"  # the one missed before comes first
    assert r["items"][0]["reason"].startswith("missed")


def test_reset(client, fake):
    start(client)
    client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")})
    client.post("/reset", params={"journal": True})
    assert client.get("/journal").json()["total"] == 0 and client.get("/live/state").json()["session"] is None


# ------------------------------------------------------------------ photos + pages

def test_capture_latest(client, fake):
    start(client)
    client.post("/grade", files={"image": ("p.jpg", write_on_paper("你"), "image/jpeg")})
    r = client.get("/capture/latest")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and float(r.headers["x-capture-ts"]) > 0


@pytest.mark.parametrize("path", ["/live", "/mirror", "/app", "/app/journal", "/print/hebrew", "/glasses"])
def test_pages_are_served(client, path):
    r = client.get(path)
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_agent_tools(client):
    names = {t["name"] for t in client.get("/agent/tools").json()["tools"]}
    assert names == {"grade_character", "compare_to_template", "choose_next_item", "compose_message", "react"}


# ------------------------------------------------------------------ hedged 14b -> 7b fallback

def test_tutor_hedge_falls_back_when_14b_is_slow(monkeypatch):
    from worn import config

    async def fake_call(model, prompt, **kw):
        await asyncio.sleep(5 if model == config.TUTOR_MODEL else 0.05)
        return {"model": model}
    monkeypatch.setattr(llm, "json_call", fake_call)
    monkeypatch.setattr(config, "TUTOR_BUDGET", 0.4)
    monkeypatch.setattr(config, "HEDGE_AFTER", 0.1)
    data, meta = asyncio.run(llm.tutor_json("x"))
    assert data["model"] == config.TUTOR_FALLBACK and meta["fallback"] and meta["ms"] < 1000


def test_tutor_hedge_prefers_14b_when_fast(monkeypatch):
    from worn import config

    async def fake_call(model, prompt, **kw):
        await asyncio.sleep(0.05)
        return {"model": model}
    monkeypatch.setattr(llm, "json_call", fake_call)
    data, meta = asyncio.run(llm.tutor_json("x"))
    assert data["model"] == config.TUTOR_MODEL and not meta["fallback"]
