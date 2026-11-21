"""Script rules: which code points belong to each language, and how text splits into
the units a learner writes one at a time (one /grade per unit)."""

from __future__ import annotations

import regex

# Unicode ranges per script, used to validate model output.
_RANGES = {
    "mandarin": r"\p{Han}",
    "hindi": r"\p{Devanagari}",
    "arabic": r"\p{Arabic}",
    "russian": r"\p{Cyrillic}",
    "hebrew": r"\p{Hebrew}",
    "greek": r"\p{Greek}",
}

_IGNORABLE = r"[\s\p{P}\p{S}‌‍ـ]"  # spaces, punctuation, ZWNJ/ZWJ, tatweel
_ARABIC_MARKS = regex.compile(r"[ً-ٰٟۖ-ۭ]")  # harakat: not written in beginner mode
_HEBREW_MARKS = regex.compile(r"[֑-ׇ]")  # niqqud: everyday Hebrew is written without vowels


def in_script(text: str, lang: str) -> bool:
    """True if every letter in text belongs to lang's script (punctuation and spaces are ignored)."""
    core = regex.sub(_IGNORABLE, "", strip_marks(text or "", lang))
    return bool(core) and regex.fullmatch(f"[{_RANGES[lang]}]+", core) is not None


def has_script(text: str, lang: str) -> bool:
    return bool(regex.search(f"[{_RANGES[lang]}]", text or ""))


def strip_marks(text: str, lang: str) -> str:
    if lang == "arabic":
        return _ARABIC_MARKS.sub("", text)
    if lang == "hebrew":
        return _HEBREW_MARKS.sub("", text)
    return text


def split_units(text: str, lang: str) -> list[str]:
    """The writable units of text, in reading order.
    mandarin: one character each. hindi: aksharas (grapheme clusters, so स्ते is one).
    arabic, hebrew: base letters, vowel marks dropped. russian, greek: letters (Greek keeps its accent)."""
    units = regex.findall(r"\X", strip_marks(text or "", lang))
    return [u for u in units if not regex.fullmatch(_IGNORABLE + "+", u)]
