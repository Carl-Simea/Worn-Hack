"""Scribi's NLU: the model plans tools, the backend executes them. Model mocked (see FakeNLU)."""

from __future__ import annotations

from test_voice import FakeNLU, nlu, say, vc  # noqa: F401  (fixtures)
from worn import voice_agent as VA


def test_one_word_commands_skip_the_model(vc, nlu):
    for w, screen in [("next", "lesson"), ("back", "words"), ("home", "learn"), ("check", "lesson"), ("help", "home")]:
        d = say(vc, w, screen)
        assert d["matcher"] == "fast" and d["intent"] != "unknown"
    assert nlu.calls == []


def test_model_plan_is_executed_server_side(vc, nlu):
    nlu.replies["teach me water in greek please"] = 'start_lesson {"language": "greek", "word": "water"}'
    d = say(vc, "teach me water in greek please", "home")
    assert d["matcher"] == "model" and d["intent"] == "select"
    assert vc.get("/session").json()["item_id"] == "water" and d["session"]["lang"] == "greek"
    assert d["actions"] == [{"tool": "open_word", "args": {"lang": "greek", "item_id": "water", "char_index": 0}}]
    st = vc.get("/app-state").json()
    assert st["screen"] == "lesson" and st["breadcrumb"][-1] == "lesson"
    steps = [s for s in vc.get("/live/state").json()["agent_steps"] if s["tool"] == "understand"]
    assert steps and "teach me water" in steps[-1]["summary"] and steps[-1]["ms"] is not None


def test_multi_step(vc, nlu):
    nlu.replies["go home then open the journal"] = 'go_home {} open_screen {"name": "journal"}'
    d = say(vc, "go home then open the journal", "lesson")
    assert [s["intent"] for s in d["steps"]] == ["home", "open"]
    assert d["nav"] == {"screen": "journal"} and [a["tool"] for a in d["actions"]] == ["go_home", "open_screen"]


def test_missing_language_uses_current_or_asks_once(vc, nlu):
    nlu.replies["I wanna learn something"] = "start_lesson {}"
    d = say(vc, "I wanna learn something", "home")
    assert d["intent"] == "ask" and "Which language" in d["say"] and d["nav"] is None
    d = say(vc, "greek", "home")  # the answer completes the pending request (no model call)
    assert d["intent"] == "learn" and d["nav"] == {"screen": "words", "lang": "greek"}
    assert vc.get("/app-state").json()["pending"] is None
    # with a current language, no question
    nlu.replies["spell water for me"] = 'spell_word {"text": "water"}'
    d = say(vc, "spell water for me", "words")
    assert d["intent"] == "select" and d["session"]["lang"] == "greek"


def test_name_question_then_answer(vc, nlu, monkeypatch):
    from worn import compose

    async def fake_name(text):
        return {"devanagari": "जॉर्डन", "arabic": "جوردن", "cyrillic": "Джордан", "hebrew": "ג'ורדן",
                "greek": "Τζόρνταν", "note": "approx"}, {"model": "fake"}
    monkeypatch.setattr(compose, "name", fake_name)
    nlu.replies["how do you write my name"] = "write_name {}"
    d = say(vc, "how do you write my name", "home")
    assert d["intent"] == "ask" and "name" in d["say"].lower()
    d = say(vc, "it's jordan", "home")
    assert d["intent"] == "write_name" and d["args"]["name"] == "Jordan"


def test_low_confidence_confirms_instead_of_guessing(vc, nlu):
    nlu.replies["the purple one maybe"] = '? open_screen {"name": "journal"}'
    d = say(vc, "the purple one maybe", "home")
    assert d["intent"] == "ask" and "Did you mean" in d["say"] and d["nav"] is None
    d = say(vc, "yes", "home")
    assert d["intent"] == "open" and d["nav"] == {"screen": "journal"}


def test_exit_goes_idle_and_wake_returns(vc, nlu):
    nlu.replies["let's exit"] = "exit_app {}"
    d = say(vc, "let's exit", "home")
    assert d["nav"] == {"screen": "idle"} and "Hey Scribi" in d["say"] and d["actions"][0]["tool"] == "exit_app"
    assert vc.get("/app-state").json()["screen"] == "idle"
    d = say(vc, "what time is it", "idle")  # no wake word: ignored, silent
    assert d["nav"] is None and d["say"] == "" and nlu.calls[-1] != "what time is it"
    d = say(vc, "hey scribi", "idle")
    assert d["intent"] == "wake" and d["nav"]["screen"] == "home"
    nlu.replies["hey scribi, learn greek"] = 'start_lesson {"language": "greek"}'
    say(vc, "let's exit", "home")
    d = say(vc, "hey scribi, learn greek", "idle")
    assert [s["intent"] for s in d["steps"]] == ["wake", "learn"] and d["nav"]["lang"] == "greek"


def test_chatter_tool_none_is_harmless(vc, nlu):
    nlu.replies["did you see the game last night"] = "none {}"
    d = say(vc, "did you see the game last night", "lesson")
    assert d["intent"] == "unknown" and d["nav"] is None and d["session"] is None


def test_model_down_falls_back_to_rules(vc, nlu):
    d = say(vc, "how do I write water in Greek", "home")  # no fake reply → timeout → rules
    assert d["matcher"] == "rules" and d["intent"] == "select" and d["session"]["lang"] == "greek"


def test_parse_lines_tolerates_aliases_and_junk():
    p = VA.parse_lines('go_home {}\nopen_screen {"name": "journal"}')
    assert [s["tool"] for s in p["steps"]] == ["go_home", "open_screen"] and p["confidence"] > 0.5
    assert VA.parse_lines("? help {}")["confidence"] < 0.5


# 40+ real-world phrasings: what the model returns for each is fixed here, so this checks the executor
# and the tool→intent mapping end to end. The live model is measured by eval_voice.py (test_data/voice_eval.md).
PHRASES = [
    ("lesson", "take me back home", "go_home {}", "home"),
    ("words", "uh go back", "go_back {}", "back"),
    ("learn", "can we go to the home screen", "go_home {}", "home"),
    ("home", "open my journal", 'open_screen {"name": "journal"}', "open"),
    ("home", "show me the daily five", 'open_screen {"name": "daily5"}', "open"),
    ("home", "how does this thing work", 'open_screen {"name": "howto"}', "open"),
    ("home", "lemme see how to use it", 'open_screen {"name": "how to use"}', "open"),
    ("home", "I'm done for today", "exit_app {}", "exit"),
    ("home", "close the app", "exit_app {}", "exit"),
    ("home", "teach me something in Arabic", 'start_lesson {"language": "arabic"}', "learn"),
    ("home", "I wanna learn some greek", 'start_lesson {"language": "greek"}', "learn"),
    ("home", "let's do hindi", 'start_lesson {"language": "hindi"}', "learn"),
    ("learn", "um the russian one", 'start_lesson {"language": "russian"}', "learn"),
    ("home", "teach me water in greek", 'start_lesson {"language": "greek", "word": "water"}', "select"),
    ("home", "how do you say hello in Mandarin", 'spell_word {"text": "hello", "language": "mandarin"}', "select"),
    ("home", "I want to spell water in Greek", 'spell_word {"text": "water", "language": "greek"}', "select"),
    ("lesson", "that was too fast", "slower {}", "slower"),
    ("lesson", "whoa slow down", "slower {}", "slower"),
    ("lesson", "can you speed it up", "faster {}", "faster"),
    ("lesson", "skip this one, it's too hard", "skip {}", "skip"),
    ("lesson", "say that again", "repeat {}", "repeat"),
    ("lesson", "wait what did you say", "repeat {}", "repeat"),
    ("lesson", "show me the strokes again", "show_again {}", "show_again"),
    ("lesson", "ok I think I'm finished", "check {}", "check"),
    ("lesson", "how did I do", "check {}", "check"),
    ("lesson", "can you check it", "check {}", "check"),
    ("lesson", "what does this mean", "explain {}", "meaning"),
    ("lesson", "what am I even writing", "explain {}", "meaning"),
    ("lesson", "go to the next one", "next {}", "next"),
    ("lesson", "move on", "next {}", "next"),
    ("lesson", "go back one", "previous {}", "previous"),
    ("home", "how do I write good morning in greek", 'compose {"text": "good morning", "language": "greek"}', "compose"),
    ("home", "write my name, Maria", 'write_name {"name": "Maria"}', "write_name"),
    ("home", "can you write my name? it's Jordan", 'write_name {"name": "Jordan"}', "write_name"),
    ("home", "what can I say", "help {}", "help"),
    ("lesson", "I'm stuck, help", "help {}", "help"),
    ("home", "yeah so the meeting got moved to three", "none {}", "unknown"),
    ("lesson", "did you see the game last night", "none {}", "unknown"),
    ("home", "uhh lessons", "open_screen {\"name\": \"lessons\"}", "open"),
    ("words", "the water one", 'start_lesson {"word": "water"}', "select"),
    ("home", "start the daily five thing", 'open_screen {"name": "daily five"}', "open"),
    ("lesson", "bye scribi", "exit_app {}", "exit"),
]


def test_forty_plus_real_world_phrasings(vc, nlu, monkeypatch):
    from worn import compose

    async def fake_compose(text, lang):
        return {"native": "καλημέρα", "romanization": "kaliméra", "back_translation": text, "chars": list("καλημέρα"),
                "note": "", "text": text}, {"model": "fake"}

    async def fake_name(text):
        return {"devanagari": "x", "arabic": "x", "cyrillic": "x", "hebrew": "x", "greek": "x", "note": ""}, {}
    monkeypatch.setattr(compose, "compose_message", fake_compose)
    monkeypatch.setattr(compose, "name", fake_name)
    bad = []
    for screen, heard, reply, want in PHRASES:
        nlu.replies[heard] = reply
        if screen in ("lesson", "words"):
            say(vc, "learn greek", "home")
            if screen == "lesson":
                say(vc, "water", "words")
                vc.post("/app-state", json={"screen": "lesson", "phase": "result"})
        d = say(vc, heard, screen)
        if d["intent"] != want:
            bad.append((heard, d["intent"], want, d["say"]))
    assert len(PHRASES) >= 40 and not bad, bad
