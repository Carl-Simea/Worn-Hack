"""compose_message (POST /compose) and name transliteration (GET /name), on qwen2.5:14b (7b fallback).

Model output is validated per script and retried once. The "note" is built in code from facts we
can check (unit count, script name, direction), so the model never gets to invent cultural facts."""

from __future__ import annotations

import regex

from . import config, llm, scripts

MAX_TEXT = 80
# Writable units per message: a Mandarin character carries a word, an alphabet letter doesn't.
MAX_UNITS = {"mandarin": 8, "hindi": 10}
MAX_ALPHA = 16

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


async def compose_message(text: str, lang: str) -> tuple[dict, dict]:
    text = (text or "").strip()
    if lang not in config.LANGS:
        raise ComposeError(f"Unknown language {lang!r}.")
    if not text:
        raise ComposeError("Say or type a short message first.")
    if len(text) > MAX_TEXT:
        raise ComposeError("That's a bit long. Try a short message, like 'thank you, friend'.")
    prompt = COMPOSE_PROMPT.format(lang_name=config.LANGS[lang]["name"], text=text.replace('"', "'"),
                                   max_units=MAX_UNITS.get(lang, MAX_ALPHA), rule=_SCRIPT_RULE[lang], roman=_ROMAN[lang])
    try:
        data, meta = await llm.tutor_json(prompt, system=SYSTEM, validate=_validator(lang), num_predict=200)
    except llm.LLMError as e:
        raise ComposeError("I couldn't turn that into a short message to write. Try simpler words.") from e
    if data.get("unsuitable"):
        raise ComposeError("Let's keep it to everyday messages, like greetings or thanks.")
    return {**data, "lang": lang, "text": text, "note": _note(lang, data["chars"])}, meta


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
    data, meta = await llm.tutor_json(NAME_PROMPT.format(name=text), system=SYSTEM,
                                      validate=_name_validator, num_predict=120)
    return {**data, "text": text, "checked": False,
            "note": "Names are written by sound, so these spellings are approximate."}, meta
