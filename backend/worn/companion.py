"""Scribi, the conversational companion: one agent (qwen2.5:14b, streaming) that chats AND acts.

Every utterance that isn't a one-word command comes here with the persona, the screen, the lesson state
(language, character facts from the content files, stroke progress, last scores, streak, mistakes, time on
this character), session memory (name, struggles, callbacks) and the last 10 turns. The model answers

    TOOLS: tool {json args} [tool {json args} ...]   (or TOOLS: none)
    SAY: one or two short spoken sentences

TOOLS comes first so the action starts while the reply is still streaming; each finished sentence of SAY
is spoken right away (TTS per sentence). If 14b is slow or down, the 7b planner (voice_agent) and then the
rule matcher take over, so voice never breaks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from typing import AsyncIterator

import httpx

from . import config, content, llm, memory, strokes
from . import voice as V
from . import voice_agent as VA
from .live import LIVE

log = logging.getLogger("worn.companion")

MODEL = __import__("os").environ.get("SCRIBI_CHAT_MODEL", config.TUTOR_FALLBACK)  # qwen2.5:7b for speed
FIRST_TOKEN_S = float(__import__("os").environ.get("WORN_CHAT_FIRST_TOKEN", "2.5"))
TOTAL_S = float(__import__("os").environ.get("WORN_CHAT_TOTAL", "3"))
ENABLED = __import__("os").environ.get("SCRIBI_CHAT", "0") == "1"

PERSONA = """You are Scribi, the voice companion inside Worn, smart glasses that teach English speakers to handwrite Mandarin, Hindi, Arabic, Russian, Hebrew and Greek on paper.
Personality: warm, quick and funny, like a hype friend who is also a great teacher. You speak out loud, so replies are SHORT: one sentence (two only if asked a question), no lists, no emoji, no markdown.
Humor comes from CONTEXT: their streak, a wobbly stroke ("that stroke said 'I'm going home early'"), a great score, taking a while, switching languages, callbacks to earlier jokes. Teasing is playful and never mean. Never joke about the person's looks, culture or intelligence, and never about the languages or cultures being taught. No religion, politics or slang lessons.
Facts: say facts about characters ONLY from FACTS below. If a fact isn't there, say you're not sure. Never invent translations: to teach a word or phrase, call a tool and the tool will say the details, so keep your own line short.
You can act. Tools: go_home, go_back, exit_app, open_screen {"name": learn|journal|daily5|howto|name|compose}, start_lesson {"language", "word"?}, spell_word {"text", "language"}, compose {"text", "language"}, write_name {"name"?}, next, previous, repeat, slower, faster, show_again, check, skip, explain, help.
Answer in exactly this format:
TOOLS: <tool {json args}> ... or none
SAY: <your spoken reply>"""

EXAMPLES = """Examples:
User: "take me home" -> TOOLS: go_home {}
SAY: Home sweet home. Where to next?
User: "why does this have 7 strokes?" (FACTS: 你, 7 strokes) -> TOOLS: none
SAY: Seven strokes because 你 packs a person on the left and a little pronoun on the right. Worth every one!
User: "ugh this is hard" (streak 0, 3 misses) -> TOOLS: none
SAY: Hard means your brain is lifting weights. One more go, I've got you.
User: "let's do greek instead" -> TOOLS: start_lesson {"language": "greek"}
SAY: Switching to Greek, very cosmopolitan of you!"""

TURNS: deque = deque(maxlen=10)  # (user, scribi, tools)
NOTES: dict = {"name": None, "struggles": [], "callbacks": deque(maxlen=5), "langs": [], "char_since": None,
               "char_key": None}


def reset() -> None:
    TURNS.clear()
    NOTES.update({"name": None, "struggles": [], "callbacks": deque(maxlen=5), "langs": [], "char_since": None,
                  "char_key": None})


# ------------------------------------------------------------------ context

def learn_name(heard: str) -> None:
    m = re.search(r"\b(?:my name is|my name's|i'm called|call me)\s+([a-z][a-z' -]{1,30})", heard.lower())
    if m:
        name = V._clean_name(m.group(1).split(" and ")[0])
        if name and len(name.split()) <= 3:
            NOTES["name"] = name


def _facts() -> str:
    s = LIVE.session
    if not s:
        return "none (no lesson open)"
    item = s.get("item") or {}
    parts = [f'current character {s["char"]} ({s.get("char_index", 0) + 1} of {s.get("total_chars", 1)}) in '
             f'"{s.get("text")}" = "{s.get("meaning")}", said {s.get("romanization")}, {s.get("lang_name")}',
             f"{s.get('stroke_count')} strokes (order: {s.get('stroke_order')})"]
    if s.get("char_romanization"):
        parts.append(f"this character sounds like {s['char_romanization']}")
    for k in ("how", "why", "note"):
        if item.get(k) or s.get(k):
            parts.append(f"{k}: {str(item.get(k) or s.get(k))[:220]}")
    return "; ".join(parts)


def _state(screen: str) -> str:
    s = LIVE.session or {}
    key = (s.get("lang"), s.get("char"))
    now = time.time()
    if key != NOTES["char_key"]:
        NOTES["char_key"], NOTES["char_since"] = key, now
        if s.get("lang") and (not NOTES["langs"] or NOTES["langs"][-1] != s["lang"]):
            NOTES["langs"].append(s["lang"])
    lines = [f"Screen: {screen}."]
    if s:
        lines.append(f"Language: {s.get('lang_name')}. On this character for {int(now - (NOTES['char_since'] or now))} s.")
    from .autograde import AUTO
    if AUTO.key and AUTO.total:
        done = [x for x in AUTO.scores if x is not None]
        lines.append(f"Writing: stroke {AUTO.stroke + 1} of {AUTO.total}" + (f", stroke scores {done}" if done else ""))
    r = LIVE.result
    if r and r.get("status") == "ok":
        lines.append(f"Last grade: {r.get('score')}/100 for {r.get('char')} ({'correct' if r.get('correct') else 'not yet'})"
                     + (f", weakest {r.get('weakest')}" if r.get("weakest") else "")
                     + (f", tip: {r.get('feedback')}" if r.get("feedback") else ""))
    elif r and r.get("status") == "no_writing":
        lines.append("Last photo: couldn't see any writing.")
    j = memory.journal(limit=30)
    streak = 0
    for e in j:
        if not e.get("correct"):
            break
        streak += 1
    misses = sum(1 for e in j[:10] if not e.get("correct"))
    lines.append(f"Streak: {streak} correct in a row; {misses} misses in the last 10 tries.")
    weak = memory.daily5(n=3)
    struggles = [f"{w['char']} ({w['reason']})" for w in weak if w.get("stats")]
    if struggles:
        lines.append("Struggled with: " + ", ".join(struggles) + ".")
    if len(NOTES["langs"]) > 1:
        lines.append("Languages this session: " + " → ".join(config.LANGS.get(l, {}).get("name", l) for l in NOTES["langs"]) + ".")
    if NOTES["name"]:
        lines.append(f"Their name: {NOTES['name']}.")
    if NOTES["callbacks"]:
        lines.append("Your earlier jokes (callbacks welcome, don't repeat): " + " | ".join(NOTES["callbacks"]))
    return "\n".join(lines)


def build_prompt(heard: str, screen: str) -> str:
    turns = "\n".join(f'User: "{u}"\nScribi ({t or "no tools"}): {a}' for u, a, t in TURNS) or "(start of conversation)"
    return (f"{EXAMPLES}\n\nFACTS: {_facts()}\nSTATE:\n{_state(screen)}\n\nConversation so far:\n{turns}\n\n"
            f'User: "{heard}" ->')


# ------------------------------------------------------------------ model stream

SENT_END = re.compile(r"(.+?[.!?…])(\s+|$)")


async def _stream_model(prompt: str) -> AsyncIterator[str]:
    """Token chunks from Ollama (streaming). Raises on transport errors."""
    body = {"model": MODEL, "prompt": prompt, "system": PERSONA, "stream": True, "keep_alive": config.KEEP_ALIVE,
            "options": {"num_ctx": llm.num_ctx(MODEL), "num_predict": 60, "temperature": 0.7, "top_p": 0.9,
                        "stop": ["\nUser:", "User:"]}}
    async with llm.client().stream("POST", "/api/generate", json=body, timeout=TOTAL_S) as r:
        r.raise_for_status()
        async for line in r.aiter_lines():
            if not line:
                continue
            d = json.loads(line)
            if d.get("response"):
                yield d["response"]
            if d.get("done"):
                break


class Turn:
    """Parses the streaming TOOLS/SAY answer. Calls on_tools once, on_sentence per finished sentence."""

    def __init__(self) -> None:
        self.buf = ""
        self.tools_line: str | None = None
        self.say = ""
        self.sent = 0  # chars of `say` already emitted as sentences

    def feed(self, chunk: str) -> tuple[str | None, list[str]]:
        self.buf += chunk
        tools = None
        if self.tools_line is None:
            m = re.search(r"TOOLS:\s*(.*?)\s*(?:\n|SAY:)", self.buf, re.S)
            if m:
                self.tools_line = tools = m.group(1).strip()
        sents = []
        m = re.search(r"SAY:\s*(.*)$", self.buf, re.S)
        if m:
            self.say = m.group(1)
            rest = self.say[self.sent:]
            while True:
                sm = SENT_END.match(rest)
                if not sm or not sm.group(2) and not rest.endswith(("!", "?", ".")):
                    break
                if not sm.group(2):  # sentence end at the very end of the buffer: wait for more text
                    break
                sents.append(sm.group(1).strip())
                self.sent += len(sm.group(0))
                rest = self.say[self.sent:]
        return tools, sents

    def finish(self) -> tuple[str | None, list[str]]:
        tools = None
        if self.tools_line is None:
            m = re.search(r"TOOLS:\s*(.*?)\s*(?:\n|SAY:|$)", self.buf, re.S)
            self.tools_line = tools = (m.group(1).strip() if m else "none")
        if not re.search(r"SAY:", self.buf):  # model skipped the format: everything after TOOLS is the reply
            self.say = re.sub(r"^.*?TOOLS:[^\n]*\n?", "", self.buf, flags=re.S).strip()
        rest = self.say[self.sent:].strip()
        sents = [s.strip() for s in re.findall(r"[^.!?…]+[.!?…]*", rest) if s.strip()]
        self.sent = len(self.say)
        return tools, sents


def parse_tools(line: str | None) -> list[dict]:
    if not line or line.strip().lower().startswith("none"):
        return []
    try:
        return VA.parse_lines(line)["steps"]
    except Exception:
        return []


def remember(heard: str, reply: str, tools: list[str]) -> None:
    TURNS.append((heard[:120], reply[:160], ", ".join(tools)))
    if re.search(r"(haha|joke|said '|said \"|lol|told|dramatic|vacation|home early|weights|cosmopolitan)", reply.lower()):
        NOTES["callbacks"].append(reply[:90])


def clean_reply(text: str) -> str:
    t = re.sub(r"[*_#`]|\b(TOOLS|SAY):", "", text or "")
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def facts_line(intent: str) -> bool:
    """Intents whose executor line carries facts (romanization, results) worth speaking after the chat line."""
    return intent in ("select", "compose", "write_name", "meaning", "learn", "ask")


async def chat(heard: str, screen: str) -> tuple[list[dict], str]:
    """One exchange (non-streaming to the caller): → (tool steps, spoken reply). Raises on timeout/error."""
    learn_name(heard)
    prompt = build_prompt(heard, screen)
    turn = Turn()

    async def run():
        async for chunk in _stream_model(prompt):
            turn.feed(chunk)
    await asyncio.wait_for(run(), TOTAL_S)
    tools_line, _ = turn.finish()
    reply = clean_reply(turn.say)
    if len(reply) > 220:
        reply = reply[:220].rsplit(".", 1)[0] + "."
    return parse_tools(turn.tools_line or tools_line), reply
