"""Voice control: POST /voice (text and real audio), /say, /app-state, and the command matcher."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import pytest

from test_routes import fake  # noqa: F401  (fixture: models mocked)
from worn import compose, voice as V, voice_agent as VA

REPO = Path(__file__).resolve().parents[2]


class FakeNLU:
    """Stands in for qwen2.5:7b: maps a heard phrase to the model's one-line reply. Unknown → model down."""

    def __init__(self):
        self.replies: dict[str, str] = {}
        self.calls: list[str] = []

    async def __call__(self, prompt: str):
        heard = prompt.rsplit('"', 2)[-2]
        self.calls.append(heard)
        if heard not in self.replies:
            raise TimeoutError("model down (test)")
        return VA.parse_lines(self.replies[heard])


@pytest.fixture
def nlu(monkeypatch):
    f = FakeNLU()
    monkeypatch.setattr(VA, "_ask_model", f)
    VA.HISTORY.clear()
    return f


@pytest.fixture
def vc(client, nlu, monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "DEDUPE_S", 0)  # tests repeat phrases on purpose
    V.reset_state()
    return client


def say(c, text, screen=None):
    data = {"text": text, **({"screen": screen} if screen else {})}
    r = c.post("/voice", data=data)
    assert r.status_code == 200, r.text
    return r.json()


def test_voice_reply_shape_and_hint(vc):
    d = say(vc, "help", "home")
    assert {"heard", "intent", "args", "say", "say_url", "nav", "hint"} <= set(d)
    assert d["intent"] == "help" and d["say"] and d["say_url"].startswith("/say?text=")


def test_never_stuck_unknown_tells_what_to_say(vc):
    d = say(vc, "purple elephant dance", "lesson")
    assert d["intent"] == "unknown" and "check" in d["say"].lower()


def test_learn_word_lesson_flow_starts_a_backend_session(vc):
    d = say(vc, "learn mandarin", "home")
    assert d["intent"] == "learn" and d["nav"] == {"screen": "words", "lang": "mandarin"}
    d = say(vc, "water", "words")
    assert d["intent"] == "select" and d["nav"]["screen"] == "lesson"
    assert d["session"]["char"] == "水" and vc.get("/session").json()["char"] == "水"
    st = vc.get("/app-state").json()
    assert st["screen"] == "lesson" and st["breadcrumb"] == ["home", "learn", "words", "lesson"]
    assert st["char"] == "水" and st["last_heard"] == "water" and st["hint"]
    # back goes to the word list of the same language
    assert say(vc, "go back", "lesson")["nav"] == {"screen": "words", "lang": "mandarin"}


def test_ordinals_and_mishearings(vc):
    say(vc, "learn hebrew", "home")
    assert say(vc, "number two", "words")["args"]["item_id"] == "one"  # test content: hello, one
    assert say(vc, "chinese please", "learn")["args"]["lang"] == "mandarin"
    assert say(vc, "greece", "learn")["args"]["lang"] == "greek"
    assert say(vc, "chek", "lesson")["intent"] == "check"


def test_next_inside_lesson_is_local_until_result(vc):
    say(vc, "learn mandarin", "home")
    say(vc, "hello", "words")
    vc.post("/app-state", json={"screen": "lesson", "phase": "your_turn"})
    d = say(vc, "next", "lesson")
    assert d["intent"] == "next" and d["nav"] is None  # glasses advance the stroke themselves
    vc.post("/app-state", json={"screen": "lesson", "phase": "result"})
    d = say(vc, "next", "lesson")
    assert d["nav"]["char_index"] == 1 and d["session"]["char"] == "好"
    assert say(vc, "previous", "lesson")["session"]["char"] == "你"


def test_check_and_meaning_use_the_session(vc):
    assert "pick a word" in say(vc, "check", "home")["say"].lower()
    say(vc, "learn mandarin", "home")
    say(vc, "water", "words")
    d = say(vc, "i'm done", "lesson")
    assert d["intent"] == "check" and d["args"]["char"] == "水" and d["nav"]["phase"] == "check"
    d = say(vc, "what does this mean", "lesson")
    assert d["intent"] == "meaning" and "water" in d["say"]


def test_open_screens_and_daily5(vc):
    assert say(vc, "open journal", "home")["nav"] == {"screen": "journal"}
    assert say(vc, "how to use", "home")["nav"] == {"screen": "howto"}
    d = say(vc, "daily five", "home")
    assert d["nav"] == {"screen": "daily5"} and len(d["args"]["items"]) == 5
    d = say(vc, "start", "daily5")
    assert d["nav"]["screen"] == "lesson" and d["nav"]["daily_index"] == 0
    assert vc.get("/app-state").json()["breadcrumb"] == ["home", "daily5", "lesson"]
    vc.post("/app-state", json={"screen": "lesson", "phase": "result"})
    assert say(vc, "next", "lesson")["nav"]["daily_index"] == 1
    # old screen ids are accepted
    assert say(vc, "home", "daily")["nav"] == {"screen": "home"}


def test_compose_lesson_phrase_goes_straight_to_the_lesson(vc):
    d = say(vc, "how do I write water in Greek", "home")
    assert d["intent"] == "select" and d["session"]["lang"] == "greek" and d["session"]["item_id"] == "water"


def test_compose_then_practice(vc, fake):
    d = say(vc, "how do I write thank you friend in Greek", "home")  # straight into the guided stroke lesson
    assert d["intent"] == "compose" and d["args"]["result"]["native"] == "ευχαριστώ φίλε"
    assert d["nav"]["screen"] == "lesson" and d["session"]["mode"] == "compose" and d["session"]["char"] == "ε"
    assert d["say"].startswith("Let's write thank you friend!")


def test_compose_without_language_asks_by_example(vc):
    d = say(vc, "how do I write good night", "home")
    assert d["intent"] == "compose" and "in Mandarin" in d["say"]


def test_write_my_name(vc, monkeypatch):
    async def fake_name(text):
        return {"devanagari": "सैम", "arabic": "سام", "cyrillic": "Сэм", "hebrew": "סם", "greek": "Σαμ",
                "note": "approx"}, {"model": "fake"}
    monkeypatch.setattr(compose, "name", fake_name)
    d = say(vc, "write my name, sam", "home")
    assert d["intent"] == "write_name" and d["args"]["name"] == "Sam"
    assert d["args"]["result"]["greek"] == "Σαμ" and d["nav"] == {"screen": "name", "name": "Sam"}


def test_app_state_post_and_live_event(vc):
    r = vc.post("/app-state", json={"screen": "learn", "listening": True, "custom": 1}).json()
    assert r["screen"] == "learn" and r["breadcrumb"] == ["home", "learn"] and "language" in r["hint"].lower()
    st = vc.get("/app-state").json()
    assert st["listening"] is True and st["custom"] == 1
    say(vc, "hebrew", "learn")
    st = vc.get("/app-state").json()
    assert st["last_voice"]["intent"] == "learn" and st["last_voice"]["ms"] >= 0
    ev = [e for e in vc.get("/live/state").json()["events"] if e["type"] == "voice"]
    assert ev and ev[-1]["data"]["heard"] == "hebrew" and ev[-1]["data"]["intent"] == "learn"


def test_voice_needs_audio_or_text(vc):
    assert vc.post("/voice", data={"screen": "home"}).status_code == 400


@pytest.mark.skipif(shutil.which("say") is None, reason="macOS say")
def test_say_returns_16k_mono_wav(vc):
    r = vc.get("/say", params={"text": "Say check when you're done."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    import io
    import wave
    with wave.open(io.BytesIO(r.content)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2) and w.getnframes() > 8000


@pytest.mark.skipif(shutil.which("say") is None, reason="macOS say")
def test_real_speech_through_whisper(vc, tmp_path):
    """Synthesized speech → faster-whisper → intent, as 16 kHz WAV (what the glasses send) and m4a."""
    pytest.importorskip("faster_whisper")
    cases = [("learn Mandarin", "home", "learn"), ("check", "lesson", "check"), ("daily five", "home", "open")]
    for text, screen, intent in cases:
        wav = tmp_path / "a.wav"
        subprocess.run(["say", "-o", str(wav), "--file-format=WAVE", "--data-format=LEI16@16000", "--channels=1",
                        text], check=True)
        d = vc.post("/voice", files={"audio": ("a.wav", wav.read_bytes(), "audio/wav")}, data={"screen": screen}).json()
        assert d["intent"] == intent, d
    if shutil.which("ffmpeg"):
        m4a = tmp_path / "a.m4a"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), str(m4a)], check=True)
        d = vc.post("/voice", files={"audio": ("a.m4a", m4a.read_bytes(), "audio/mp4")}, data={"screen": "home"}).json()
        assert d["intent"] == "open"


def test_silence_is_not_a_command(vc):
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000)
    d = vc.post("/voice", files={"audio": ("s.wav", buf.getvalue(), "audio/wav")}, data={"screen": "home"}).json()
    assert d["intent"] == "unknown" and "didn't hear" in d["say"]


def test_parser_units():
    ctx = {"lang": "mandarin", "items": [{"id": "hello", "meaning": "hello"}, {"id": "water", "meaning": "water"}]}
    p = V.parse("how would you say good luck in russian", "home", ctx)
    assert p == {"intent": "compose", "args": {"text": "good luck", "lang": "russian"}}
    assert V.parse("my name is anna maria", "home", ctx)["args"]["name"] == "Anna Maria"
    assert V.parse("slow down please", "lesson", ctx)["intent"] == "slower"
    assert V.parse("show me again", "lesson", ctx)["intent"] == "show_again"
    assert V.parse("skip this", "lesson", ctx)["intent"] == "skip"
    assert V.norm_screen("help") == "howto" and V.norm_screen("daily") == "daily5"


def test_content_matcher_is_used_when_present(monkeypatch):
    f = REPO / "content" / "tools" / "voice_match.py"
    if not f.exists():
        pytest.skip("C's matcher not in this checkout")
    monkeypatch.setattr(V.config, "CONTENT_DIR", REPO / "content")
    monkeypatch.setattr(V, "_C", None)
    ctx = {"lang": "greek", "items": [], "langs": {"greek": {"items": [{"id": "water", "meaning": "water"}]}}}
    r = V.parse_any("learn greek", "home", ctx)
    assert r["intent"] == "learn" and r["args"]["lang"] == "greek" and r["matcher"] == "content"
    r = V.parse_any("how do I write good morning in Greek", "home", ctx)
    assert r["intent"] == "compose" and r["args"] == {"text": "good morning", "lang": "greek"}


def test_content_matcher_start_and_pick(monkeypatch):
    f = REPO / "content" / "tools" / "voice_match.py"
    if not f.exists():
        pytest.skip("C's matcher not in this checkout")
    monkeypatch.setattr(V.config, "CONTENT_DIR", REPO / "content")
    monkeypatch.setattr(V, "_C", None)
    items = [{"id": i, "meaning": i.replace("_", " ")} for i in ("hello", "thank_you", "water", "friend", "one")]
    ctx = {"lang": "greek", "items": items, "langs": {"greek": {"items": items}}}
    assert V.parse_any("start", "daily5", ctx)["intent"] == "next"
    assert V.parse_any("practice it", "compose", ctx)["intent"] == "practice"
    r = V.parse_any("the second one", "words", ctx)
    assert r["intent"] == "select" and r["args"]["item_id"] == "thank_you"
    assert V.parse_any("how do I write water and Greek", "home", ctx)["args"].get("lang") == "greek"
    assert V.parse_any("great", "learn", ctx)["args"]["lang"] == "greek"


def test_content_matcher_start_and_pick(monkeypatch):
    f = REPO / "content" / "tools" / "voice_match.py"
    if not f.exists():
        pytest.skip("C's matcher not in this checkout")
    monkeypatch.setattr(V.config, "CONTENT_DIR", REPO / "content")
    monkeypatch.setattr(V, "_C", None)
    items = [{"id": i, "meaning": i.replace("_", " ")} for i in ("hello", "thank_you", "water", "friend", "one")]
    ctx = {"lang": "greek", "items": items, "langs": {"greek": {"items": items}}}
    assert V.parse_any("start", "daily5", ctx)["intent"] == "next"
    assert V.parse_any("practice it", "compose", ctx)["intent"] == "practice"
    r = V.parse_any("the second one", "words", ctx)
    assert r["intent"] == "select" and r["args"]["item_id"] == "thank_you"
    assert V.parse_any("how do I write water and Greek", "home", ctx)["args"].get("lang") == "greek"
    assert V.parse_any("great", "learn", ctx)["args"]["lang"] == "greek"
    assert V.parse_any("Hey Scribi, learn Greek", "home", ctx)["args"]["lang"] == "greek"


def test_assistant_is_scribi_app_is_worn(vc):
    assert "Hi, I'm Scribi." in say(vc, "go home", "learn")["say"]
    assert "Just talk to Scribi" in say(vc, "how to use", "home")["say"]
    assert say(vc, "hey scribi, open journal", "home")["nav"] == {"screen": "journal"}


def test_back_works_with_display_name_breadcrumbs(vc):
    vc.post("/app-state", json={"screen": "words", "lang": "mandarin", "breadcrumb": ["Home", "Learn", "Mandarin"]})
    assert say(vc, "back", "words")["nav"] == {"screen": "learn"}
    vc.post("/app-state", json={"screen": "lesson", "breadcrumb": ["Home", "Daily 5", "你"]})
    assert say(vc, "back", "lesson")["nav"]["screen"] in ("words", "daily5")


@pytest.mark.parametrize("chatter", ["that's the thing, that's definitely", "yeah I think we should go back to the hotel later",
                                     "I was in Greece last summer it was great", "okay so the next thing on the agenda is lunch"])
def test_room_chatter_is_harmless(vc, chatter):
    for screen in ("home", "lesson", "words"):
        d = say(vc, chatter, screen)
        assert d["intent"] == "unknown" and d["nav"] is None and d["session"] is None, (screen, d)
