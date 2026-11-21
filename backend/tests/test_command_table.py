"""The deterministic command table always wins over the AI: 30 casual phrasings (filler, wake word, slang)
must each do the right action. No model is called for any of them."""

from __future__ import annotations

import pytest

from test_voice import FakeNLU, nlu, say, vc  # noqa: F401

PHRASES = [  # screen, heard, intent, check(nav/args)
    ("lesson", "take me home", "home", {"screen": "home"}),
    ("lesson", "um hey Scribi, can you take me back home please", "home", {"screen": "home"}),
    ("learn", "Scribi, take me to the homepage.", "home", {"screen": "home"}),
    ("words", "main menu", "home", {"screen": "home"}),
    ("words", "start over", "home", {"screen": "home"}),
    ("words", "go back", "back", {}),
    ("words", "uh, back please", "back", {}),
    ("words", "undo", "back", {}),
    ("home", "exit", "exit", {"screen": "idle"}),
    ("home", "ok bye Scribi", "exit", {"screen": "idle"}),
    ("home", "I'm done", "exit", {"screen": "idle"}),
    ("home", "close the app", "exit", {"screen": "idle"}),
    ("home", "learn Hebrew", "learn", {"lang": "hebrew"}),
    ("home", "hey scribi teach me greek", "learn", {"lang": "greek"}),
    ("home", "can you teach me something in hebrew", "learn", {"lang": "hebrew"}),
    ("home", "switch to Chinese", "learn", {"lang": "mandarin"}),
    ("home", "let's do mandarin", "learn", {"lang": "mandarin"}),
    ("home", "open greek", "learn", {"lang": "greek"}),
    ("home", "Scribi, help me write.", "open", {"screen": "compose"}),
    ("home", "write this word", "open", {"screen": "compose"}),
    ("home", "how do I write my name", "open", {"screen": "name"}),
    ("home", "Scribi, help me write my name.", "open", {"screen": "name"}),
    ("home", "my name is Jordan", "write_name", {"name": "Jordan"}),
    ("home", "how do I write water in greek", "select", {"lang": "greek"}),
    ("lesson", "next", "next", None),
    ("lesson", "say that again", "repeat", None),
    ("lesson", "whoa, slow down", "slower", None),
    ("lesson", "um, check it please", "check", None),
    ("lesson", "skip this one", "skip", None),
    ("lesson", "what does this mean", "meaning", None),
    ("home", "help", "help", None),
    ("home", "show me my journal", "open", {"screen": "journal"}),
]


def test_thirty_casual_phrasings_always_do_the_right_thing(vc, nlu, monkeypatch):
    from worn import compose

    async def fake_name(text):
        return {"devanagari": "x", "arabic": "x", "cyrillic": "x", "hebrew": "x", "greek": "x", "note": ""}, {}
    monkeypatch.setattr(compose, "name", fake_name)
    assert len(PHRASES) >= 30
    bad = []
    for screen, heard, want, chk in PHRASES:
        if screen in ("lesson", "words"):
            say(vc, "learn greek", "home")
            if screen == "lesson":
                say(vc, "water", "words")
                vc.post("/app-state", json={"screen": "lesson", "phase": "result"})
        d = say(vc, heard, screen)
        ok = d["intent"] == want
        if ok and chk:
            got = {**(d.get("nav") or {}), **(d.get("args") or {})}
            if d.get("session"):
                got["lang"] = d["session"]["lang"]
            ok = all(str(got.get(k)).lower() == str(v).lower() for k, v in chk.items())
        if ok and d["intent"] not in ("meaning", "help") and not d["say"]:
            ok = False  # every action is confirmed out loud
        if not ok:
            bad.append((heard, d["intent"], d.get("nav"), d["say"][:60]))
    assert not bad, bad
    assert nlu.calls == []  # none of them needed the model


def test_every_action_is_confirmed_in_a_few_words(vc, nlu):
    assert say(vc, "take me home", "words")["say"].startswith("Going home!")
    assert say(vc, "learn hebrew", "home")["say"].startswith("Opening Hebrew!")
    d = say(vc, "how do I write water in greek", "home")
    assert d["say"].startswith("Let's write water!")


def test_duplicate_clip_is_not_executed_twice(client, nlu):
    from worn import voice as V
    V.reset_state()
    a = say(client, "learn greek", "home")
    b = say(client, "learn greek", "home")  # the glasses posted the same clip again
    assert a["intent"] == "learn" and b.get("duplicate") and b["actions"] == []
