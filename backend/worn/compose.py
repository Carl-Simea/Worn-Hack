"""compose_message (POST /compose) and name transliteration (GET /name), on qwen2.5:14b (7b fallback).

Model output is validated per script and retried once. The "note" is built in code from facts we
can check (unit count, script name, direction), so the model never gets to invent cultural facts."""

from __future__ import annotations

import regex

from . import config, llm, scripts

MAX_TEXT = 80
# Writable units per message: a Mandarin character carries a word, an alphabet letter doesn't.
MAX_UNITS = {"mandarin": 8, "hindi": 10}
MAX_ALPHA = 24  # e.g. Russian "nice to meet you" = 20 letters

SYSTEM = ("You are a careful language tutor for English speakers. You translate short everyday messages. "
          "You never add religious, political or slang content, and you never state cultural facts. "
          "You always answer with one JSON object and nothing else.")

_SCRIPT_RULE = {
    "mandarin": "Simplified Chinese characters only (no traditional characters, no pinyin in native)",
    "hindi": "Devanagari script only",
    "arabic": "Arabic script only, no vowel marks (harakat)",
    "russian": "Cyrillic script only",
    "hebrew": "Hebrew letters only, no vowel points (niqqud)",
    "greek": "Greek letters only (modern monotonic Greek, with accents)",
}
_ROMAN = {
    "mandarin": "pinyin with tone marks",
    "hindi": "simple English-style romanization",
    "arabic": "simple English-style romanization",
    "russian": "simple English-style romanization",
    "hebrew": "simple English-style romanization",
    "greek": "simple English-style romanization with stress accents",
}

COMPOSE_PROMPT = """Translate this short message from English into {lang_name} for a beginner to hand-write.
Message: "{text}"

Rules:
- native: the translation, natural and polite, as SHORT as possible (at most {max_units} written characters/letters). {rule}.
- romanization: {roman}.
- back_translation: a literal English translation of your native text.
- suitable: false if the message is religious, political, slang, rude or unsafe; otherwise true.

JSON only: {{"native": "...", "romanization": "...", "back_translation": "...", "suitable": true}}"""


# ------------------------------------------------------------------ 14b answer cache
# Every qwen2.5:14b answer is kept (data/llm_cache.json). When a request had to fall back to 7b, the
# learner gets the 7b answer right away and 14b redoes it in the background, so the next identical
# request gets the stronger model's answer instantly.
import asyncio
import json
import logging
import threading

log = logging.getLogger("worn.compose")
_cache_lock = threading.Lock()
_pending: set[str] = set()
COMPOSE_CAP = 12.0  # nobody is mid-stroke here: allow more time than the grade's decide step


def _cache_path():
    return config.DATA_DIR / "llm_cache.json"


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        try:
            return json.loads(_cache_path().read_text(encoding="utf-8")).get(key)
        except Exception:
            return None


def _cache_put(key: str, value: dict) -> None:
    with _cache_lock:
        try:
            data = json.loads(_cache_path().read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data[key] = value
        _cache_path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


async def _upgrade(key: str, prompt: str, validate) -> None:
    """Background: ask 14b with no tight budget and cache its answer."""
    if key in _pending:
        return
    _pending.add(key)
    try:
        data = await llm.json_call(config.TUTOR_MODEL, prompt, system=SYSTEM, validate=validate, timeout=60,
                                   num_predict=200, temperature=0.2)
        if not data.get("unsuitable"):
            _cache_put(key, data)
            log.info("cached 14b answer for %s", key)
    except Exception as e:
        log.warning("14b upgrade failed for %s: %s", key, e)
    finally:
        _pending.discard(key)


async def _cached_tutor(key: str, prompt: str, validate, num_predict: int) -> tuple[dict, dict]:
    hit = _cache_get(key)
    if hit:
        return hit, {"model": f"{config.TUTOR_MODEL} (cached)", "ms": 0, "fallback": False, "cached": True}
    data, meta = await llm.tutor_json(prompt, system=SYSTEM, validate=validate, num_predict=num_predict, cap=COMPOSE_CAP)
    if not meta.get("fallback"):
        if not data.get("unsuitable"):
            _cache_put(key, data)
    else:
        asyncio.get_running_loop().create_task(_upgrade(key, prompt, validate))
    return data, meta


def _key(kind: str, lang: str, text: str) -> str:
    return f"{kind}:{lang}:{_norm(text)}"


def _norm(s: str) -> str:
    return " ".join(regex.sub(r"[\p{P}\p{S}]+", " ", (s or "").lower()).split())


# Brief: no religious, political or slang content. A deterministic word list decides (the models'
# own "suitable" flag proved erratic: 14b once refused "see you tomorrow").
BLOCKED = {
    "vote", "votes", "voting", "election", "elections", "party", "president", "politics", "political", "government",
    "war", "army", "flag", "god", "allah", "jesus", "christ", "church", "mosque", "temple", "synagogue", "pray",
    "prayer", "religion", "religious", "bible", "quran", "koran", "torah", "gun", "guns", "kill", "die", "dead",
    "hate", "drug", "drugs", "weed", "sex", "sexy", "damn", "hell", "shit", "fuck", "bitch", "stupid", "idiot",
}


def unsuitable(text: str) -> bool:
    return any(w in BLOCKED for w in _norm(text).split())


def _from_phrasebook(text: str, lang: str) -> dict | None:
    """content/phrases/examples.json (agent C, hand-checked): {"phrases": {"good morning": {"mandarin":
    {"native", "romanization"}, ...}}}. Used before any model, like names/examples.json."""
    try:
        book = json.loads((config.CONTENT_DIR / "phrases" / "examples.json").read_text(encoding="utf-8")).get("phrases", {})
    except Exception:
        return None
    want = _norm(text)
    for phrase, langs in book.items():
        if _norm(phrase) == want and isinstance(langs, dict) and langs.get(lang, {}).get("native"):
            e = langs[lang]
            units = scripts.split_units(e["native"], lang)
            if units:
                out = {"native": e["native"], "romanization": e.get("romanization", ""), "back_translation": phrase,
                       "chars": units}
                if e.get("note"):
                    out["form_note"] = e["note"]  # e.g. gendered / formal form, from C's checked list
                return out
    return None


def _from_lessons(text: str, lang: str) -> dict | None:
    """A message that IS a lesson phrase ('thank you', 'hello', 'water'...) comes from the checked
    lesson content, never from a model."""
    from . import content
    lesson = content.load().get(lang)
    if not lesson:
        return None
    want = _norm(text)
    for it in lesson["items"]:
        if want and _norm(it.get("meaning") or "") == want and it.get("text"):
            units = scripts.split_units(it["text"], lang)
            return {"native": it["text"], "romanization": it.get("romanization") or "",
                    "back_translation": it.get("meaning"), "chars": units or list(it.get("chars") or [])}
    return None


class ComposeError(ValueError):
    """A friendly, user-facing reason the message could not be composed."""


def _note(lang: str, units: list[str]) -> str:
    meta = config.LANGS[lang]
    direction = "right to left" if meta["rtl"] else "left to right"
    kind = {"mandarin": "character", "hindi": "syllable block", "arabic": "letter", "russian": "letter",
            "hebrew": "letter", "greek": "letter"}[lang]
    # Script facts only (from the team's lesson notes), never cultural claims.
    extra = {
        "arabic": " Practice each letter in its isolated form first; add the dots after the main stroke.",
        "hindi": " The top line is usually drawn last.",
        "russian": " This is printed Cyrillic; cursive handwriting looks different.",
        "hebrew": " These are block print letters; everyday handwriting uses a cursive style.",
        "greek": " Some letters look familiar but sound different.",
    }.get(lang, "")
    return f"{len(units)} {kind}{'s' if len(units) != 1 else ''} to write in {meta['script']}, {direction}.{extra}"


def _validator(lang: str):
    def check(d: dict) -> dict:
        if d.get("suitable") is False:
            return {"unsuitable": True}
        native = str(d.get("native") or "").strip()
        if not native or not scripts.in_script(native, lang):
            raise ValueError(f"native {native!r} is not in the {lang} script")
        units = scripts.split_units(native, lang)
        if not units:
            raise ValueError("no writable units")
        if len(units) > MAX_UNITS.get(lang, MAX_ALPHA):
            raise ValueError(f"too long: {len(units)} units")
        rom = str(d.get("romanization") or "").strip()
        back = str(d.get("back_translation") or "").strip()
        if not rom or not back:
            raise ValueError("missing romanization or back_translation")
        return {"native": native, "romanization": rom[:120], "back_translation": back[:160], "chars": units}
    return check


CHECK_PROMPT = """A beginner wants to write this English message in {lang_name}: "{text}".
Proposed {lang_name} text: {native}

Step 1: translate the proposed text into natural English, ignoring the message above.
Step 2: would a native speaker use it to say the message? Small differences are fine: politeness or intensity ("thanks" = "thank you" = "thank you very much", "very pleased" = "nice to meet you"), word order, or a dropped "my"/"dear". A different meaning, a missing key word (like "tomorrow" or "friend"), or nonsense is not.
JSON only: {{"english": "...", "same_meaning": true or false}}"""


async def check_translation(text: str, lang: str, native: str) -> tuple[bool | None, str]:
    """Independent 14b check: back-translate the native text and judge it against the request.
    Caught every wrong phrase in our test set (nonsense Hebrew, 'Пока' for 'see you tomorrow', ...).
    Returns (same_meaning, english) or (None, "") when the checker is unavailable."""
    try:
        d = await llm.json_call(config.TUTOR_MODEL, CHECK_PROMPT.format(lang_name=config.LANGS[lang]["name"],
                                                                        text=text.replace('"', "'"), native=native),
                                system=SYSTEM, timeout=10, num_predict=80, temperature=0.0)
    except Exception as e:
        log.warning("translation check unavailable: %s", e)
        return None, ""
    return bool(d.get("same_meaning")), str(d.get("english") or "")[:120]


def _pinyin(native: str) -> str | None:
    try:
        from pypinyin import Style, pinyin
    except ImportError:
        return None
    han = [c for c in native if scripts.in_script(c, "mandarin")]
    return " ".join(s[0] for s in pinyin("".join(han), style=Style.TONE)) if han else None


async def compose_message(text: str, lang: str) -> tuple[dict, dict]:
    text = (text or "").strip()
    if lang not in config.LANGS:
        raise ComposeError(f"Unknown language {lang!r}.")
    if not text:
        raise ComposeError("Say or type a short message first.")
    if len(text) > MAX_TEXT:
        raise ComposeError("That's a bit long. Try a short message, like 'thank you, friend'.")

    def done(d: dict, meta: dict) -> tuple[dict, dict]:
        if lang == "mandarin":
            d = {**d, "romanization": _pinyin(d["native"]) or d["romanization"]}
        note = _note(lang, d["chars"])
        if d.get("form_note"):
            note = f"{d['form_note']} {note}"
        return {**d, "lang": lang, "text": text, "note": note}, meta

    if unsuitable(text):
        raise ComposeError("Let's keep it to everyday messages, like greetings or thanks.")
    lesson_hit = _from_lessons(text, lang)
    if lesson_hit:
        return done({**lesson_hit, "verified": True, "check": lesson_hit["back_translation"]},
                    {"model": "lesson content (checked)", "ms": 0, "fallback": False})
    book_hit = _from_phrasebook(text, lang)
    if book_hit:
        return done({**book_hit, "verified": True, "check": book_hit["back_translation"]},
                    {"model": "phrasebook (checked)", "ms": 0, "fallback": False})
    key = _key("compose", lang, text)
    hit = _cache_get(key)
    if hit and hit.get("verified"):
        return done(hit, {"model": f"{config.TUTOR_MODEL} (checked, cached)", "ms": 0, "fallback": False, "cached": True})

    base = COMPOSE_PROMPT.format(lang_name=config.LANGS[lang]["name"], text=text.replace('"', "'"),
                                 max_units=MAX_UNITS.get(lang, MAX_ALPHA), rule=_SCRIPT_RULE[lang], roman=_ROMAN[lang])
    prompt = base
    meta: dict = {}
    for attempt in range(2):
        try:
            data, meta = await llm.tutor_json(prompt, system=SYSTEM, validate=_validator(lang), num_predict=200,
                                              cap=COMPOSE_CAP)
        except llm.LLMError as e:
            raise ComposeError("I couldn't turn that into a short message to write. Try simpler words.") from e
        if data.get("unsuitable"):  # the word list above already passed it; the model's flag is erratic
            prompt = f"{base}\n\nThis is an everyday, harmless message. Translate it. JSON only."
            continue
        ok, english = await check_translation(text, lang, data["native"])
        meta = {**meta, "checked_by": config.TUTOR_MODEL, "attempts": attempt + 1}
        if ok:
            data = {**data, "verified": True, "check": english}
            _cache_put(key, data)
            return done(data, meta)
        if ok is None:  # checker down: answer, clearly marked unchecked, and don't cache
            return done({**data, "verified": False, "check": ""}, meta)
        log.info("compose check failed for %s/%r: %r means %r", lang, text, data["native"], english)
        prompt = (f"{base}\n\nA previous answer, {data['native']}, actually means \"{english}\", not \"{text}\". "
                  f"Write it so it means exactly \"{text}\". JSON only.")
    raise ComposeError("I'm not confident I can write that one correctly yet. Try something simpler, "
                       "like 'thank you, friend'.")


# ------------------------------------------------------------------ names

NAME_PROMPT = """Write the English name "{name}" by its SOUND in five scripts, the way a native speaker would spell a foreign name.

JSON only:
{{"devanagari": "Hindi Devanagari", "arabic": "Arabic script, no vowel marks", "cyrillic": "Russian Cyrillic", "hebrew": "Hebrew letters, no vowel points", "greek": "Greek letters"}}"""

_NAME_SCRIPTS = {"devanagari": "hindi", "arabic": "arabic", "cyrillic": "russian", "hebrew": "hebrew", "greek": "greek"}


def _name_validator(d: dict) -> dict:
    out = {}
    for key, script in _NAME_SCRIPTS.items():
        v = str(d.get(key) or "").strip()
        if not v or not scripts.in_script(v, script):
            raise ValueError(f"{key} {v!r} is not in the right script")
        out[key] = scripts.strip_marks(v, script)[:40]
    return out


def checked_names() -> dict:
    """content/names/examples.json (agent C): names checked by hand in all five scripts."""
    import json
    try:
        return json.loads((config.CONTENT_DIR / "names" / "examples.json").read_text(encoding="utf-8")).get("names", {})
    except Exception:
        return {}


async def name(text: str) -> tuple[dict, dict]:
    text = (text or "").strip()
    if not text or len(text) > 40 or not regex.fullmatch(r"[\p{L}][\p{L} '\-]*", text):
        raise ComposeError("Type just a name, like 'Maya'.")
    known = checked_names().get(text.lower())
    if known and all(known.get(k) for k in _NAME_SCRIPTS):
        return {**{k: known[k] for k in _NAME_SCRIPTS}, "text": text, "checked": True,
                "note": "Names are written by sound, so these spellings are approximate."}, {"model": "checked list", "ms": 0}
    data, meta = await _cached_tutor(_key("name", "all", text), NAME_PROMPT.format(name=text), _name_validator, 120)
    return {**data, "text": text, "checked": False,
            "note": "Names are written by sound, so these spellings are approximate."}, meta


# ------------------------------------------------------------------ prefetch
# Phrases a demo visitor is likely to try, precomputed with 14b at startup (skips cached ones).
PREFETCH = ["thank you, friend", "hello friend", "good morning", "nice to meet you", "see you tomorrow",
            "thank you very much"]
PREFETCH_NAMES = ["Jordan", "Alex", "Sara", "Chris", "Priya", "Omar"]


async def prefetch() -> None:
    for text in PREFETCH:
        for lang in config.LANG_ORDER:
            try:
                await compose_message(text, lang)  # checks + caches
            except ComposeError as e:
                log.info("prefetch %s/%r: %s", lang, text, e)
    for n in PREFETCH_NAMES:
        key = _key("name", "all", n)
        if n.lower() not in checked_names() and not _cache_get(key):
            await _upgrade(key, NAME_PROMPT.format(name=n), _name_validator)
