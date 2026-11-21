"""Scribi's understanding: transcript + screen + state + last turns → a plan of tool calls.

Single-word commands ("next", "back", "check", a language on the language list, a word on the word list)
take the instant rule path. Everything else goes to qwen2.5:7b (warm, JSON mode) with the tool list. Missing
details are filled from the current state, or Scribi asks ONE short question and remembers the pending
request; low-confidence plans are confirmed in one line instead of guessed. If the model is slow or down,
the rule matcher answers, so voice never breaks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque

from . import config, llm
from . import voice as V

log = logging.getLogger("worn.voice_agent")

MODEL = config.TUTOR_FALLBACK  # qwen2.5:7b: fast, kept warm with the others
BUDGET_S = float(__import__("os").environ.get("WORN_VOICE_BUDGET", "2.0"))
CONFIRM_BELOW = 0.5
LANG_Q = "Which language: Mandarin, Hindi, Arabic, Russian, Hebrew or Greek?"

TOOLS = {
    "go_home": "home screen", "go_back": "previous screen", "exit_app": "stop / bye / exit / close the app",
    "open_screen": "args.name: learn | journal | daily5 | howto | name | compose",
    "start_lesson": "args.language, args.word (optional: hello, thank you, water, friend, one)",
    "spell_word": "args.text, args.language: how to write/spell a word or phrase",
    "write_name": "args.name (the person's name, if said), args.language (optional)",
    "compose": "args.text, args.language: help writing a longer message",
    "next": "", "previous": "", "repeat": "say it again", "slower": "too fast", "faster": "too slow",
    "show_again": "replay the stroke animation", "check": "I'm done, grade my writing", "skip": "skip this one",
    "explain": "what does this mean / what is this", "help": "what can I say", "none": "not talking to Scribi",
}
TOOL_TO_INTENT = {"go_home": "home", "go_back": "back", "exit_app": "exit", "open_screen": "open",
                  "next": "next", "previous": "previous", "repeat": "repeat", "slower": "slower",
                  "faster": "faster", "show_again": "show_again", "check": "check", "skip": "skip",
                  "explain": "meaning", "help": "help"}

SYSTEM = ("You are Scribi, the voice assistant inside Worn, a smart-glasses app that teaches English speakers to "
          "handwrite Mandarin, Hindi, Arabic, Russian, Hebrew and Greek. You turn what the wearer says into tool "
          "calls. Answer with one JSON object only.")

PROMPT = """Tools: {tools}

Reply with one line per tool call: tool_name {{json args}}. Nothing else.
- Several lines only for several requests in order ("go home then open the journal").
- "home" anywhere (e.g. "take me back home") means go_home. "back"/"return" alone means go_back.
- "exit", "bye", "close", "stop listening", "I'm done for today" mean exit_app.
- In a lesson: "I'm done", "finished", "how did I do" mean check; "too fast" means slower.
- Omit args you don't know. Never invent a language that wasn't said.
- Chatter not meant for Scribi: none {{}}. If you are unsure what they want, start the line with ?
Examples:
"take me back home" -> go_home {{}}
"I want to spell water in Hebrew" -> spell_word {{"text": "water", "language": "hebrew"}}
"teach me something in Arabic" -> start_lesson {{"language": "arabic"}}
"skip this one, it's too hard" -> skip {{}}
"go home then open the journal" -> go_home {{}}
open_screen {{"name": "journal"}}
"how do you write my name" -> write_name {{}}
"so yeah the meeting is at three" -> none {{}}
"how does this thing work" -> open_screen {{"name": "howto"}}
"I'm stuck, help" -> help {{}}
"maybe the purple thing" -> ? help {{}}

Screen: {screen}. Language: {lang}. Word: {word}.
Recent turns:
{turns}
"{heard}" ->"""

HISTORY: deque = deque(maxlen=3)  # last turns: (heard, tools, say)

FAST_WORDS = {"next", "back", "home", "check", "repeat", "previous", "skip", "slower", "faster", "help", "done",
              "again", "menu", "replay", "exit", "stop", "bye", "start", "yes", "no"}
FILLER = re.compile(r"\b(please|okay|ok|um|uh|erm|hmm|so|now|like|just|scribi)\b")


def _lang(v) -> str | None:
    if not v:
        return None
    v = V.norm(str(v))
    return v if v in config.LANGS else V.find_lang(v)


def _describe(step: dict) -> str:
    t, a = step["tool"], step.get("args") or {}
    lang = config.LANGS.get(_lang(a.get("language")) or "", {}).get("name", "")
    return {"go_home": "go home", "go_back": "go back", "exit_app": "close Worn",
            "open_screen": f"open {a.get('name', 'that screen')}", "start_lesson": f"learn {lang or 'a language'}"
            + (f", the word {a['word']}" if a.get("word") else ""),
            "spell_word": f"write {a.get('text', 'that')} in {lang or 'a language'}",
            "compose": f"write {a.get('text', 'that')} in {lang or 'a language'}",
            "write_name": "write your name" + (f", {a['name']}" if a.get("name") else "")}.get(t, t.replace("_", " "))


ALIASES = {"learn": "start_lesson", "learn_language": "start_lesson", "select": "start_lesson",
           "open_word": "start_lesson", "open": "open_screen", "home": "go_home", "back": "go_back",
           "exit": "exit_app", "meaning": "explain", "replay": "show_again", "spell": "spell_word",
           "translate": "compose", "name": "write_name", "grade": "check", "done": "check"}
CALL = re.compile(r"(\?)?\s*([a-z_]{3,})\s*(\{[^{}]*\})?")


def parse_lines(text: str) -> dict:
    """'? spell_word {"text": "water"}' (one or more calls, any line breaks) → the plan dict (validated)."""
    steps, unsure = [], False
    for m in CALL.finditer((text or "").replace("`", " ")):
        name = ALIASES.get(m.group(2), m.group(2))
        if name not in TOOLS:
            continue
        unsure |= bool(m.group(1))
        try:
            args = json.loads(m.group(3)) if m.group(3) else {}
        except json.JSONDecodeError:
            args = {}
        steps.append([name, args if isinstance(args, dict) else {}])
    return _validate({"steps": steps, "conf": 0.35 if unsure else 0.9})


async def _ask_model(prompt: str) -> dict:
    body = {"model": MODEL, "prompt": prompt, "system": SYSTEM, "stream": False, "keep_alive": config.KEEP_ALIVE,
            "options": {"num_ctx": llm.num_ctx(MODEL), "num_predict": 48, "temperature": 0.1, "stop": ["\n\n", '\n"', ' ->']}}
    r = await llm.client().post("/api/generate", json=body, timeout=BUDGET_S)
    r.raise_for_status()
    return parse_lines(r.json().get("response", ""))


def _validate(d: dict) -> dict:
    steps = d.get("steps")
    if isinstance(d.get("tool"), str):  # a single call instead of a list
        steps = [{"tool": d["tool"], "args": d.get("args") or {}}]
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a non-empty list")
    out = []
    for s in steps[:3]:
        if isinstance(s, list) and s:
            s = {"tool": s[0], "args": s[1] if len(s) > 1 else {}}
        if isinstance(s, str):
            s = {"tool": s, "args": {}}
        if not isinstance(s, dict) or s.get("tool") not in TOOLS:
            raise ValueError(f"unknown tool {s!r}; use one of {', '.join(TOOLS)}")
        out.append({"tool": s["tool"], "args": s.get("args") if isinstance(s.get("args"), dict) else {}})
    try:
        conf = float(d.get("conf", d.get("confidence", 0.8)))
    except (TypeError, ValueError):
        conf = 0.8
    return {"steps": out, "say": str(d.get("say") or "")[:140], "confidence": max(0.0, min(1.0, conf))}


def to_intents(steps: list[dict], ctx: dict, heard: str) -> tuple[list[dict], dict | None]:
    """Model tools → executor intents. Returns (intents, ask) where ask = {say, pending} when a detail is missing."""
    out: list[dict] = []
    cur_lang = ctx.get("lang")
    for s in steps:
        t, a = s["tool"], s.get("args") or {}
        lang = _lang(a.get("language") or a.get("lang"))
        if t == "none":
            continue
        if t in TOOL_TO_INTENT:
            intent = TOOL_TO_INTENT[t]
            args = {}
            if t == "open_screen":
                name = V.norm(str(a.get("name") or a.get("screen") or ""))
                scr = V.norm_screen({"daily five": "daily5", "daily 5": "daily5", "how to use": "howto",
                                     "write my name": "name", "help me write": "compose", "languages": "learn",
                                     "lessons": "learn"}.get(name, name))
                if scr == "home" and name not in ("home", ""):
                    scr = next((k for k, ws in V.OPEN_WORDS.items() if any(V._has(name, w) for w in ws)), "home")
                args = {"screen": scr}
                if scr == "home":
                    intent, args = "home", {}
            out.append({"intent": intent, "args": args})
        elif t == "start_lesson":
            lang = lang or (None if "language" in heard.lower() else cur_lang)
            if not lang:
                return out, {"say": LANG_Q, "pending": {"tool": t, "args": a, "need": "lang"}}
            word = V.norm(str(a.get("word") or ""))
            items = ((ctx.get("langs") or {}).get(lang) or {}).get("items") or []
            it = V.find_item(word, items) if word else None
            if it:
                out.append({"intent": "select", "args": {"lang": lang, "item_id": it["id"]}})
            elif word:
                out.append({"intent": "compose", "args": {"text": word, "lang": lang}})
            else:
                out.append({"intent": "learn", "args": {"lang": lang}})
        elif t in ("spell_word", "compose"):
            text = str(a.get("text") or a.get("word") or "").strip()
            if not text:
                return out, {"say": "What would you like to write?", "pending": {"tool": t, "args": a, "need": "text"}}
            lang = lang or cur_lang
            if not lang:
                return out, {"say": LANG_Q, "pending": {"tool": t, "args": {**a, "text": text}, "need": "lang"}}
            out.append({"intent": "compose", "args": {"text": text, "lang": lang}})
        elif t == "write_name":
            name = V._clean_name(str(a.get("name") or ""))
            if not name or V.norm(name) in ("my name", "name", "me", "my"):
                return out, {"say": "Sure! What's your name?", "pending": {"tool": t, "args": {}, "need": "name"}}
            out.append({"intent": "write_name", "args": {"name": name}})
    return out, None


def _resolve_pending(heard: str, pending: dict, ctx: dict) -> tuple[list[dict], dict | None] | None:
    t = V.norm(heard)
    need = pending.get("need")
    if need == "confirm":
        if re.search(r"\b(yes|yeah|yep|sure|ok|okay|do it|right|correct|please)\b", t):
            return to_intents(pending["steps"], ctx, heard)
        if re.search(r"\b(no|nope|nah|cancel|never mind|wrong)\b", t):
            return [], {"say": "Okay. " + V.HINTS.get(V.norm_screen(ctx.get("screen")), V.HINTS["home"]), "pending": None}
        return None
    if need == "lang":
        lang = V.find_lang(t)
        if not lang:
            return None
        return to_intents([{"tool": pending["tool"], "args": {**pending["args"], "language": lang}}], ctx, heard)
    if need == "name":
        m = re.search(r"(?:my name is|i'm|i am|it's|its|call me|name is)\s+(.+)$", t)
        name = V._clean_name(m.group(1) if m else t)
        if not name or len(name.split()) > 4:
            return None
        return to_intents([{"tool": "write_name", "args": {"name": name}}], ctx, heard)
    if need == "text":
        m = re.search(r"^(.+?)(?:\s+in\s+(\w+))?$", t)
        return to_intents([{"tool": pending["tool"], "args": {**pending["args"], "text": m.group(1),
                                                              **({"language": m.group(2)} if m.group(2) else {})}}],
                          ctx, heard)
    return None


def fast_path(heard: str, screen: str, ctx: dict) -> dict | None:
    """One-word commands stay instant (rule matcher). Returns an intent dict or None."""
    t = FILLER.sub(" ", V.norm(heard))
    words = t.split()
    if len(words) != 1:
        return None
    w = words[0]
    if w in FAST_WORDS or (screen == "learn" and V.find_lang(w)) or (
            screen == "words" and V.find_item(w, ctx.get("items") or [])) or (screen == "daily5" and w == "start"):
        if w in ("exit", "stop", "bye"):
            return {"intent": "exit", "args": {}}
        if w in ("yes", "no"):
            return None  # only meaningful with a pending question
        r = V.parse_any(w, screen, ctx)
        return r if r["intent"] != "unknown" else None
    return None


EXACT_INTENTS = ("learn", "compose", "write_name", "select")

# Room speech the glasses mic picks up ("Are you ready?", "Okay, I'm gonna ask you again.") must not fire
# lesson commands. A gated intent from a longer sentence needs its trigger phrase; questions aimed at
# someone else are chatter.
GATED_TRIGGERS = {
    "check": r"\b(i'?m|i am|i think i'?m) (done|finished)\b|\bhow did i do\b|\b(check|grade|score)\b|\bi finished\b|\bthat'?s it\b",
    "repeat": r"\bsay (that|it) again\b|\bwhat did you say\b|\brepeat\b|\bone more time\b|\bdidn'?t (hear|catch)\b|\bpardon\b",
    "skip": r"\bskip\b|\btoo hard\b",
    "next": r"\bnext\b|\bmove on\b|\bgo on\b|\bkeep going\b",
    "previous": r"\bprevious\b|\bback one\b|\bone before\b|\blast one\b",
    "exit": r"\b(bye|goodbye|exit|quit)\b|\bclose (the )?app\b|\bdone for (today|now)\b|\bstop listening\b",
    "slower": r"\btoo fast\b|\bslow(er| down)?\b",
    "faster": r"\btoo slow\b|\bspeed (it )?up\b|\bfaster\b",
    "show_again": r"\b(show|replay|watch)\b",
    "meaning": r"\bmean(ing|s)?\b|\bwhat (is|am i|'s) (this|that|it|i)\b|\bwhat am i (even )?writing\b",
}
OTHER_PERSON_Q = re.compile(r"^(?:(?:ok|okay|so|um|uh|well|hey|wait)\s+)*(are|were|did|do|have|will|would|is) (you|he|she|they|we)\b")
FILLER_START = re.compile(r"^(?:(?:ok|okay|so|um|uh|well|alright|hey|scribi|please|now|oh|wait)\s+)+")


def gate(intents: list[dict], heard: str) -> list[dict]:
    """Drop lesson commands that room speech triggered. Short commands (<= 3 words) always pass."""
    t = V.norm(heard)
    core = FILLER_START.sub("", t)
    n = len(core.split())
    out = []
    for i in intents:
        name = i["intent"]
        if name in GATED_TRIGGERS and n > 3:
            if OTHER_PERSON_Q.match(t):
                continue  # "did you see the next train": a question to someone in the room
            if not re.search(GATED_TRIGGERS[name], core):
                continue
            if name == "repeat" and re.search(r"\b(i'?m|i am) (gonna|going to) (ask|say|tell)\b", core):
                continue  # "I'm gonna ask you again": the speaker repeating, not a request
        if name == "learn" and not V.find_lang(t) and not re.search(r"\b(learn|lesson|teach|languages?)\b", t):
            continue  # "Are you ready?" isn't "learn <current language>"
        out.append(i)
    return out


LANG_ALT = r"(mandarin|chinese|hindi|arabic|russian|hebrew|greek)"
EXACT = [
    ("learn", re.compile(rf"^(?:(?:let'?s|i want to|i wanna|can we|please)\s+)?(?:learn|study|practi[cs]e|do|start|open)\s+(?:some\s+)?{LANG_ALT}(?:\s+please)?$")),
    ("compose", re.compile(rf"^how (?:do|would|can|should) (?:i|you|we) (?:write|say|spell) (?P<text>[a-z' ]{{1,40}}?) in {LANG_ALT}$")),
    ("write_name", re.compile(r"^(?:write|spell) my name,? (?P<name>[a-z' -]{1,30})$|^my name is (?P<name2>[a-z' -]{1,30})$")),
]


def exact_path(heard: str, screen: str, ctx: dict) -> dict | None:
    """Canonical sentences ("learn Hindi", "how do I write water in Greek", "write my name, Sam") are answered
    by rules: instant and never misrouted by the model. Anything looser goes to the model."""
    t = re.sub(r"^(?:(?:ok|okay|so|um|uh|hey|scribi)\s+)+", "", V.norm(heard))
    for intent, rx in EXACT:
        m = rx.match(t)
        if not m:
            continue
        if intent == "learn":
            return {"intent": "learn", "args": {"lang": V.find_lang(m.group(1))}}
        if intent == "compose":
            return {"intent": "compose", "args": {"text": m.group("text").strip(), "lang": V.find_lang(m.group(2))}}
        name = V._clean_name(m.group("name") or m.group("name2") or "")
        if name:
            return {"intent": "write_name", "args": {"name": name}}
    return None


async def plan(heard: str, screen: str, state: dict, ctx: dict) -> dict:
    """→ {intents: [{intent, args}], say?, pending?, via: fast|pending|model|rules|wake, model_say, ms, confidence}"""
    t0 = time.perf_counter()
    t = V.norm(heard)
    ms = lambda: round((time.perf_counter() - t0) * 1000)  # noqa: E731
    raw = (heard or "").lower()

    if screen == "idle":
        woke = bool(re.search(r"\b(scribi|scribby|scribie|scrubby|scribe|skribi|wake up)\b", raw)) or not t
        if not woke:
            return {"intents": [], "via": "idle", "ms": ms()}
        if not t or t in ("hey", "hi", "hello", "wake up"):
            return {"intents": [{"intent": "wake", "args": {}}], "via": "wake", "ms": ms()}
        inner = await plan(heard, "home", state, ctx)
        inner["intents"] = [{"intent": "wake", "args": {}}] + inner["intents"]
        return inner
    if not t:
        return {"intents": [{"intent": "unknown", "args": {"reason": "silence"}}], "via": "fast", "ms": ms()}

    pending = state.get("pending")
    if pending:
        res = _resolve_pending(heard, pending, {**ctx, "screen": screen})
        if res is not None:
            intents, ask = res
            return {"intents": intents, **(ask or {}), "pending": (ask or {}).get("pending"), "via": "pending",
                    "ms": ms()}

    fp = fast_path(heard, screen, ctx) or exact_path(heard, screen, ctx)
    if fp:
        return {"intents": [{"intent": fp["intent"], "args": fp["args"]}], "via": "fast", "ms": ms()}

    if OTHER_PERSON_Q.match(t) and len(t.split()) > 2:
        return {"intents": [{"intent": "unknown", "args": {"reason": "chatter"}}], "via": "fast", "ms": ms()}
    word = (LIVE_word(state) or "none")
    prompt = PROMPT.format(
        tools="; ".join(f"{k}({v})" if v else k for k, v in TOOLS.items()), screen=screen,
        lang=config.LANGS.get(ctx.get("lang") or "", {}).get("name", "none"), word=word,
        turns="\n".join(f'- "{h}" -> {tl} ("{sy}")' for h, tl, sy in HISTORY) or "- (none)", heard=heard)
    try:
        data = await asyncio.wait_for(_ask_model(prompt), BUDGET_S + 0.2)
    except (asyncio.TimeoutError, llm.LLMError, Exception) as e:  # never break voice on the model
        log.info("voice model fallback (%s): %r", type(e).__name__, heard)
        r = V.parse_any(heard, screen, ctx)
        kept = gate([{"intent": r["intent"], "args": r["args"]}], heard)
        return {"intents": kept or [{"intent": "unknown", "args": {"reason": "chatter"}}], "via": "rules",
                "error": f"{type(e).__name__}: {str(e)[:80]}", "ms": ms()}

    steps = data["steps"]
    for st_ in steps:  # small, certain fixes on top of the model
        if st_["tool"] == "go_back" and re.search(r"\bhome\b", t):
            st_["tool"] = "go_home"
        if (len(steps) == 1 and st_["tool"] not in ("help", "compose", "spell_word", "write_name")
                and re.search(r"\b(help|stuck|what can i say)\b", t) and not re.search(r"help me (write|spell)", t)):
            st_["tool"], st_["args"] = "help", {}
        if st_["tool"] in ("go_home", "go_back") and re.search(r"\b(exit|bye|goodbye|close)\b", t):
            st_["tool"] = "exit_app"
    if all(s["tool"] == "none" for s in steps):
        return {"intents": [{"intent": "unknown", "args": {"reason": "chatter"}}], "via": "model", "ms": ms(),
                "tools": steps, "confidence": data["confidence"]}
    if data["confidence"] < CONFIRM_BELOW:
        guess = " then ".join(_describe(s) for s in steps if s["tool"] != "none")
        return {"intents": [], "say": f"Did you mean: {guess}? Say yes or no.",
                "pending": {"need": "confirm", "steps": steps}, "via": "model", "tools": steps,
                "confidence": data["confidence"], "ms": ms()}
    intents, ask = to_intents(steps, ctx, heard)
    kept = gate(intents, heard)
    if intents and not kept and not ask:
        return {"intents": [{"intent": "unknown", "args": {"reason": "chatter"}}], "via": "model", "ms": ms(),
                "tools": steps, "confidence": data["confidence"]}
    intents = kept
    return {"intents": intents, **(ask or {}), "pending": (ask or {}).get("pending"), "via": "model",
            "tools": steps, "model_say": data["say"], "confidence": data["confidence"], "ms": ms()}


def LIVE_word(state: dict) -> str | None:  # noqa: N802
    from .live import LIVE
    s = LIVE.session or {}
    return s.get("meaning") if state.get("screen") == "lesson" else None


def remember(heard: str, intents: list[dict], say: str) -> None:
    HISTORY.append((heard[:80], json.dumps([i["intent"] for i in intents]), (say or "")[:60]))
