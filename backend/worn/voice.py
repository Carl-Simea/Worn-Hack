"""Voice control for the glasses: local speech-to-text (faster-whisper) + a deterministic, fuzzy
command matcher + spoken replies (macOS `say`). Every reply tells the wearer what they can say next.

Intent names are the ones the glasses app handles (agent D):
home, back, open(screen), learn(lang), select(lang,item_id), next, previous, repeat, slower, show_again,
check, skip, compose(text,lang), write_name(name), meaning, help, unknown.
"""

from __future__ import annotations

import difflib
import hashlib
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("worn.voice")

# ------------------------------------------------------------------ app state (what the glasses show)

SCREENS = ("home", "learn", "words", "lesson", "name", "compose", "daily5", "journal", "howto")
SCREEN_ALIASES = {"daily": "daily5", "daily_5": "daily5", "help": "howto", "how_to": "howto", "howtouse": "howto",
                  "review": "daily5", "languages": "learn", "word": "words", "write_name": "name"}
OPEN_SCREENS = ("learn", "journal", "daily5", "howto", "name", "compose")

HINTS = {
    "home": 'Say "learn Mandarin", "daily five", "journal", "write my name", or "help".',
    "learn": 'Say a language: Mandarin, Hindi, Arabic, Russian, Hebrew or Greek. Or "back".',
    "words": 'Say a word: hello, thank you, water, friend or one. Or "back".',
    "lesson": 'Say "check" when you\'re done. Or "repeat", "slower", "next", "skip", "what does this mean".',
    "name": 'Say "write my name" and your name, like "write my name, Sam". Or "home".',
    "compose": 'Say "how do I write" something "in" a language, like "how do I write good morning in Greek".',
    "daily5": 'Say "start" for your Daily 5, or "next", "back", "home".',
    "journal": 'Say "back" or "home". Or "learn" and a language.',
    "howto": 'Say "home", "back", "learn Mandarin", "check", "next", "repeat", or "write my name".',
}

_state_lock = threading.Lock()
STATE: dict[str, Any] = {}


def reset_state() -> None:
    with _state_lock:
        STATE.clear()
        STATE.update({"screen": "home", "breadcrumb": ["home"], "phase": None, "lang": None, "item_id": None,
                      "char_index": 0, "listening": False, "last_heard": None, "last_voice": None,
                      "hint": HINTS["home"], "updated": time.time(), "source": "backend"})


reset_state()


def norm_screen(screen: str | None) -> str:
    s = (screen or "home").strip().lower()
    s = SCREEN_ALIASES.get(s, s)
    return s if s in SCREENS else "home"


def breadcrumb(scr: str, old: str | None, old_bc: list) -> list:
    """Canonical trail so "back" is predictable. A lesson remembers whether it came from Daily 5 or Help me write."""
    if scr == "lesson":
        origin = old if old in ("daily5", "compose", "words") else next(
            (s for s in ("daily5", "compose") if s in old_bc), "words")
        return {"daily5": ["home", "daily5", "lesson"], "compose": ["home", "compose", "lesson"]}.get(
            origin, ["home", "learn", "words", "lesson"])
    return {"home": ["home"], "learn": ["home", "learn"], "words": ["home", "learn", "words"]}.get(scr, ["home", scr])


def update_state(fields: dict, source: str = "glasses") -> dict:
    with _state_lock:
        old_screen = STATE.get("screen")
        for k, v in fields.items():
            if v is not None or k in ("phase",):
                STATE[k] = v
        STATE["screen"] = scr = norm_screen(STATE.get("screen"))
        if not isinstance(fields.get("breadcrumb"), list) or not fields.get("breadcrumb"):
            STATE["breadcrumb"] = breadcrumb(scr, old_screen, STATE.get("breadcrumb") or ["home"])
        if "hint" not in fields or not fields.get("hint"):
            STATE["hint"] = HINTS.get(scr, HINTS["howto"])
        STATE["updated"] = time.time()
        STATE["source"] = source
        return dict(STATE)


def get_state() -> dict:
    with _state_lock:
        return dict(STATE)


# ------------------------------------------------------------------ speech to text

STT_MODEL = os.environ.get("WORN_STT_MODEL", "base")
_stt = None
_stt_lock = threading.Lock()
VOCAB = ("Worn. Commands: home, back, next, previous, repeat, slower, show me again, check, I'm done, skip, help, "
         "what can I say, what does this mean, open learn, open journal, daily five, write my name, "
         "how do I write thank you in Hindi. Learn Mandarin, Hindi, Arabic, Russian, Hebrew, Greek. "
         "Hello, thank you, water, friend, one.")


class STTError(RuntimeError):
    pass


def _model():
    global _stt
    with _stt_lock:
        if _stt is None:
            from faster_whisper import WhisperModel
            t = time.time()
            _stt = WhisperModel(STT_MODEL, device="cpu", compute_type="int8")
            log.info("whisper %s loaded in %.1fs", STT_MODEL, time.time() - t)
        return _stt


def warm_stt() -> None:
    try:
        _model()
    except Exception as e:  # never take the server down for speech
        log.warning("speech model not loaded: %s", e)


def decode_audio(audio: bytes, filename: str = "audio.wav"):
    """→ float32 mono 16 kHz. PCM WAV is read directly; anything else goes through ffmpeg."""
    import io
    import wave

    import numpy as np
    if audio[:4] == b"RIFF":
        try:
            with wave.open(io.BytesIO(audio)) as w:
                if w.getsampwidth() == 2:
                    ch, rate = w.getnchannels(), w.getframerate()
                    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
                    if ch > 1:
                        x = x.reshape(-1, ch).mean(axis=1)
                    if rate != 16000 and x.size:
                        n = int(x.size * 16000 / rate)
                        x = np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x).astype(np.float32)
                    return x
        except wave.Error:
            pass
    try:
        p = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                            "-ar", "16000", "pipe:1"], input=audio, capture_output=True, timeout=20, check=True)
    except Exception as e:
        raise STTError(f"couldn't decode the audio ({Path(filename or '').suffix or 'unknown'}): {e}")
    return np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768


def transcribe(audio: bytes, filename: str = "audio.wav") -> str:
    """Audio bytes (wav/m4a/aac/mp3/...) → English text. Runs on this Mac, no network."""
    if not audio or len(audio) < 200:
        return ""
    try:
        m = _model()
    except Exception as e:
        raise STTError(f"speech model unavailable: {e}")
    pcm = decode_audio(audio, filename)
    if pcm.size < 1600:  # < 0.1 s
        return ""
    try:
        segs, _info = m.transcribe(pcm, language="en", beam_size=1, vad_filter=True,
                                   initial_prompt=VOCAB, condition_on_previous_text=False,
                                   without_timestamps=True)
        text = " ".join(s.text.strip() for s in segs).strip()
    except Exception as e:
        raise STTError(f"couldn't read the audio: {e}")
    # whisper hallucinates the prompt or "Thank you." on silence
    if text.lower().startswith("worn. commands") or len(text) > 200:
        return ""
    return text


# ------------------------------------------------------------------ text to speech

SAY_DIR = config.DATA_DIR / "say"
_say_lock = threading.Lock()


def say_file(text: str) -> Path:
    """macOS `say` → 16 kHz mono 16-bit WAV, cached by text."""
    text = re.sub(r"\s+", " ", text or "").strip()[:400]
    if not text:
        raise ValueError("nothing to say")
    SAY_DIR.mkdir(parents=True, exist_ok=True)
    out = SAY_DIR / (hashlib.sha1(text.encode()).hexdigest()[:16] + ".wav")
    if out.exists() and out.stat().st_size > 100:
        return out
    with _say_lock:
        if out.exists() and out.stat().st_size > 100:
            return out
        tmp = out.with_suffix(".tmp.wav")
        subprocess.run(["say", "-o", str(tmp), "--file-format=WAVE", "--data-format=LEI16@16000", "--channels=1",
                        "--", text], check=True, timeout=20, capture_output=True)
        tmp.replace(out)
    return out


# ------------------------------------------------------------------ command matching

LANG_WORDS = {
    "mandarin": ["mandarin", "chinese", "mandarine", "manderin", "mandrin", "china"],
    "hindi": ["hindi", "hindy", "indy", "hindu", "devanagari"],
    "arabic": ["arabic", "arabik", "arab", "arabian"],
    "russian": ["russian", "russia", "rushin", "cyrillic", "russhian"],
    "hebrew": ["hebrew", "ebrew", "hebrews", "he brew", "hibrew", "israeli"],
    "greek": ["greek", "greece", "greeks", "creek", "grik"],
}
ORDINALS = {"one": 1, "first": 1, "1": 1, "two": 2, "second": 2, "2": 2, "to": 2, "too": 2, "three": 3, "third": 3,
            "3": 3, "four": 4, "fourth": 4, "for": 4, "4": 4, "five": 5, "fifth": 5, "5": 5}

# (intent, phrases). Matched as whole-word phrases after normalizing; first hit wins, so order matters.
PHRASES: list[tuple[str, tuple[str, ...]]] = [
    ("help", ("what can i say", "what do i say", "help me", "help", "commands", "what can i do", "how do i use",
              "how to use", "options")),
    ("meaning", ("what does this mean", "what does it mean", "what is this", "what's this", "meaning",
                 "what does that mean", "translate this", "what is that")),
    ("home", ("go home", "home screen", "main menu", "home", "start over", "menu")),
    ("back", ("go back", "back", "previous screen", "return", "exit", "cancel")),
    ("check", ("check my writing", "check it", "check this", "check", "i'm done", "im done", "i am done", "done",
               "finished", "grade it", "grade", "take a picture", "take a photo", "look at this", "how did i do",
               "i'm finished", "ready")),
    ("show_again", ("show me again", "show again", "show it again", "again please", "watch again", "replay",
                    "show me", "one more time")),
    ("slower", ("slower", "slow down", "more slowly", "slowly", "too fast")),
    ("repeat", ("repeat", "say it again", "say again", "say that again", "pardon", "what did you say", "again")),
    ("skip", ("skip", "skip this", "skip it", "pass")),
    ("previous", ("previous", "go previous", "last one", "the one before", "before")),
    ("next", ("next", "next one", "continue", "keep going", "move on", "go on", "forward", "next word")),
]
OPEN_WORDS = {
    "learn": ("learn", "lessons", "lesson", "languages", "language", "learning"),
    "journal": ("journal", "my journal", "history", "progress", "journey"),
    "daily5": ("daily five", "daily 5", "daily", "review", "daily review", "daley five", "daly five", "daily fives"),
    "howto": ("how to use", "instructions", "tutorial"),
    "name": ("write my name", "my name", "name"),
    "compose": ("help me write", "compose", "translator", "translate"),
}


def norm(text: str) -> str:
    t = (text or "").lower().replace("’", "'")
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _has(t: str, phrase: str) -> bool:
    return re.search(rf"(?:^|\s){re.escape(phrase)}(?:$|\s)", t) is not None


def _fuzzy_word(word: str, choices: list[str], cutoff: float = 0.8) -> str | None:
    m = difflib.get_close_matches(word, choices, n=1, cutoff=cutoff)
    return m[0] if m else None


def find_lang(t: str) -> str | None:
    for lang, words in LANG_WORDS.items():
        if any(_has(t, w) for w in words):
            return lang
    flat = {w: lang for lang, ws in LANG_WORDS.items() for w in ws if " " not in w}
    for tok in t.split():
        if len(tok) >= 4:
            hit = _fuzzy_word(tok, list(flat))
            if hit:
                return flat[hit]
    return None


def _strip_lang_tail(s: str) -> str:
    return re.sub(r"\s+(?:in|into|to|using)\s+\w+(?:\s+\w+)?$", "", s).strip()


def find_item(t: str, items: list[dict]) -> dict | None:
    """'water', 'thank you', 'number two', 'the second one' → a lesson item."""
    for it in sorted(items, key=lambda i: -len(norm(i.get("meaning") or ""))):
        for key in {norm(it.get("meaning") or ""), norm(it.get("id", "").replace("_", " "))}:
            if key and _has(t, key):
                return it
    m = re.search(r"(?:number|word|item|the)\s+(\w+)", t)
    if m and m.group(1) in ORDINALS and ORDINALS[m.group(1)] <= len(items):
        return items[ORDINALS[m.group(1)] - 1]
    keys = {norm(it.get("meaning") or ""): it for it in items}
    hit = difflib.get_close_matches(t, list(keys), n=1, cutoff=0.75)
    return keys[hit[0]] if hit else None


COMPOSE_RE = [
    r"how (?:do|would|can|should) (?:i|you|we) (?:write|say|spell) (?P<text>.+?) in (?P<lang>[\w ]+)$",
    r"(?:write|say|spell|translate) (?P<text>.+?) (?:in|into|to) (?P<lang>[\w ]+)$",
    r"what(?:'s| is) (?P<text>.+?) in (?P<lang>[\w ]+)$",
    r"how (?:do|would|can) (?:i|you) (?:write|say|spell) (?P<text>.+)$",
    r"help me write (?P<text>.+)$",
]
NAME_RE = [
    r"(?:write|spell|show) my name(?: is| as)?,? (?P<name>.+)$",
    r"my name is (?P<name>.+)$",
    r"(?:write|spell) the name (?P<name>.+)$",
    r"(?:my )?name,? (?P<name>.+)$",
]


def _clean_name(raw: str) -> str:
    n = re.sub(r"\b(please|thanks|thank you)\b", "", raw).strip(" ,.")
    n = re.sub(r"^(?:is|it's|its|as)\s+", "", n)
    return " ".join(w.capitalize() for w in n.split()[:4])


def parse(text: str, screen: str | None, ctx: dict) -> dict:
    """→ {intent, args}. ctx: {"lang", "items": [lesson items of ctx lang], "langs": {...}}"""
    t = norm(text)
    screen = norm_screen(screen)
    if not t:
        return {"intent": "unknown", "args": {"reason": "silence"}}

    # 1. sentences with a payload come first ("write my name, Sam", "how do I write water in Hindi")
    for pat in NAME_RE[:3] + ([NAME_RE[3]] if screen == "name" else []):
        m = re.search(pat, t)
        if m and _clean_name(m.group("name")):
            return {"intent": "write_name", "args": {"name": _clean_name(m.group("name"))}}
    for pat in COMPOSE_RE:
        m = re.search(pat, t)
        if not m:
            continue
        gd = m.groupdict()
        body = gd["text"].strip()
        lang = find_lang(gd.get("lang") or "") if gd.get("lang") else None
        if gd.get("lang") and not lang:  # "in a letter", not a language: keep the whole phrase
            body = f"{body} in {gd['lang']}"
        if not lang:
            lang = find_lang(body) or ctx.get("lang")
            body = _strip_lang_tail(body) if find_lang(body) else body
        body = re.sub(r"^(?:the word|the phrase|a|the)\s+", "", body).strip(" ?")
        if body and body not in ("it", "this", "that"):
            return {"intent": "compose", "args": {"text": body, "lang": lang}}

    # 2. on the word list (or in a lesson), a bare word picks it: "water", "number two"
    lang = find_lang(t)
    items = ctx.get("items") or []
    if screen in ("words",) and items:
        it = find_item(t, items)
        if it and not any(_has(t, p) for p in ("next", "back", "home", "help")):
            return {"intent": "select", "args": {"lang": ctx.get("lang"), "item_id": it["id"]}}

    # 3. "learn Mandarin", "Hebrew", "open journal"
    if lang and (screen in ("learn", "home", "words", "howto", "journal", "daily5") or
                 any(_has(t, w) for w in ("learn", "open", "start", "teach", "practice", "study", "lesson",
                                          "switch", "go to", "let's do", "try"))):
        it = find_item(t, items_for(ctx, lang)) if screen != "learn" else None
        args = {"lang": lang}
        if it and any(_has(t, w) for w in (norm(it.get("meaning") or ""),)):
            return {"intent": "select", "args": {"lang": lang, "item_id": it["id"]}}
        return {"intent": "learn", "args": args}

    is_open = any(_has(t, w) for w in ("open", "go to", "show", "take me to", "start", "let's", "launch"))
    for scr in ("daily5", "journal", "name", "compose", "howto"):
        if any(_has(t, w) for w in OPEN_WORDS[scr]):
            if scr == "name" and screen == "name":
                break  # "name" on the name screen without a name: fall through to help
            return {"intent": "open", "args": {"screen": scr}}
    if any(_has(t, w) for w in OPEN_WORDS["learn"]) and (is_open or screen != "lesson"):
        return {"intent": "open", "args": {"screen": "learn"}}
    if is_open and any(_has(t, w) for w in ("how to use", "instructions", "tutorial")):
        return {"intent": "open", "args": {"screen": "howto"}}

    # 4. plain commands
    for intent, phrases in PHRASES:
        if any(_has(t, p) for p in phrases):
            return {"intent": intent, "args": {}}
    if screen == "daily5" and any(_has(t, w) for w in ("start", "go", "begin", "yes", "okay", "ok", "let's go")):
        return {"intent": "next", "args": {"start": True}}

    # 5. single-word fuzzy rescue for mishearings ("chek", "nex", "skipp")
    words = {p: i for i, ps in PHRASES for p in ps if " " not in p}
    for tok in t.split():
        hit = _fuzzy_word(tok, list(words), cutoff=0.8) if len(tok) >= 4 else None
        if hit:
            return {"intent": words[hit], "args": {"fuzzy": tok}}
    if lang:
        return {"intent": "learn", "args": {"lang": lang}}
    return {"intent": "unknown", "args": {}}


def items_for(ctx: dict, lang: str) -> list[dict]:
    return ((ctx.get("langs") or {}).get(lang) or {}).get("items") or []


# ------------------------------------------------------------------ C's shared matcher first (D runs the same on-device)

_C_MAP = {"how_write": "compose", "word": "select"}


def _c_matcher():
    try:
        import importlib.util
        f = config.CONTENT_DIR / "tools" / "voice_match.py"
        if not f.exists():
            return None
        spec = importlib.util.spec_from_file_location("worn_c_voice_match", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        log.warning("content voice matcher unavailable: %s", e)
        return None


_C = None


def parse_any(text: str, screen: str | None, ctx: dict) -> dict:
    """C's content matcher (shared with the glasses' on-device fallback) first, then ours for anything it misses."""
    global _C
    screen = norm_screen(screen)
    t = norm(text)
    # screen-specific words the shared matcher reads differently
    if screen == "daily5" and t in ("start", "go", "begin", "yes", "ok", "okay", "let's go", "lets go", "start daily five"):
        return {"intent": "next", "args": {"start": True}, "matcher": "backend"}
    if screen == "compose" and any(_has(t, w) for w in ("practice", "practise", "write it", "let's write", "lets write")):
        return {"intent": "practice", "args": {}, "matcher": "backend"}
    if _C is None:
        _C = _c_matcher() or False
    if _C:
        try:
            r = _C.match(text, screen)
        except Exception as e:
            log.warning("content matcher failed on %r: %s", text, e)
            r = {"intent": None}
        intent = r.get("intent")
        if intent:
            a = dict(r.get("args") or {})
            intent = _C_MAP.get(intent, intent)
            if "language" in a:
                a["lang"] = a.pop("language")
            if intent == "select":
                a = {"lang": a.get("lang") or ctx.get("lang"), "item_id": a.get("word")}
                if not a["lang"] or not any(i["id"] == a["item_id"] for i in items_for(ctx, a["lang"])):
                    intent = None
            if intent == "open":
                a["screen"] = norm_screen(a.get("screen"))
            if intent == "compose" and not a.get("text"):
                intent = None
            if intent:
                return {"intent": intent, "args": a, "matcher": "content"}
    r = parse(text, screen, ctx)
    return {**r, "matcher": "backend"}
