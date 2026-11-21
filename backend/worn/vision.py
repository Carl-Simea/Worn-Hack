"""Tier 3 perception: qwen2.5vl:7b reads the handwriting and we compare its reading to the target."""

from __future__ import annotations

import base64
import io
import unicodedata

from PIL import Image, ImageOps

from . import llm

LANG_NAMES = {
    "mandarin": "Mandarin Chinese (simplified hanzi)",
    "hindi": "Hindi (Devanagari)",
    "arabic": "Arabic (isolated letter)",
    "russian": "Russian (printed Cyrillic)",
    "hebrew": "Hebrew (block print letter)",
    "greek": "Greek",
}

PROMPT = """Look at this photo of handwriting on paper, taken from smart glasses (may be tilted or blurry).

Step 1: Read it. What {lang_name} character/letter is actually written? Answer with the character itself, exactly as you read it, even if it is not the one the learner wanted.
Step 2: The learner (an English-speaking beginner) was TRYING to write "{char}" ({uname}). Compare what you read with "{char}".

Reply with JSON only:
{{"seen": "the character you read, or empty if no writing", "score": 0-100, "fix": "if it is not a clean {char}: the ONE most important fix in plain English, max 12 words, otherwise empty"}}

Score 90-100 for a clear {char}, 60-89 for a recognizable but messy {char}, under 40 if it is a different character or unreadable."""
# No phrase-level hints (romanization/meaning of the whole phrase) in this prompt: they made the model
# leave "seen" empty, so every grade during an active session came back as score 0 (fixed 2026-11-20).


def prep_image(raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((1024, 1024))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=88)
    return out.getvalue()


CASED = {"russian", "greek", "latin"}  # alphabets with capital and small letters


def _base(s: str) -> str:
    """Greek/Latin letter without accents (Greek tonos etc.). Never used for Devanagari or
    Arabic, where combining marks are real parts of the character."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def parse_grade(data: dict, char: str, lang: str = "") -> dict:
    seen = str(data.get("seen") or "").strip()
    score = int(max(0, min(100, float(data.get("score") or 0))))
    fix = str(data.get("fix") or "").strip().splitlines()[0][:120] if data.get("fix") else ""
    if not seen and char in fix:
        seen = char  # the model named the char in its fix but left "seen" blank
    if not seen:
        return {"correct": False, "score": 0, "seen": "",
                "feedback": "I can't see your writing, hold the paper closer."}
    note = None
    if char in seen:
        # The model read exactly the target. That IS a correct character; its style score must
        # never turn it into a miss (we don't penalize personal handwriting style).
        correct = True
        score = max(score, 65)
    elif lang in CASED and char.casefold() in seen.casefold():
        correct = True  # capital vs small letter: a form choice, not a mistake
        score = max(min(score, 85), 70)
        other = next((s for s in seen if s.casefold() == char.casefold()), seen)
        note = f"That's {other}, the {'small' if other.islower() else 'capital'} form of {char}. Both count!"
    elif lang in ("greek", "latin") and _base(char).casefold() in _base(seen).casefold():
        correct = True
        score = max(min(score, 80), 65)
        note = f"Yes, {char}! Add the accent mark on top."
    else:
        correct = False
    if not correct:
        score = min(score, 45)
        if not fix:
            fix = f"That looks like {seen}, not {char}. Watch the animation again."
        feedback = fix
    else:
        feedback = note or (f"Nice! That's {char}." if score >= 85 else f"Good, {char} is readable.")
    return {"correct": correct, "score": score, "seen": seen, "feedback": feedback}


async def grade(jpeg: bytes, char: str, lang: str) -> tuple[dict, dict]:
    """Returns (result, meta). Raises llm.LLMError / asyncio.TimeoutError when the model is unavailable."""
    prompt = PROMPT.format(lang_name=LANG_NAMES.get(lang, lang), char=char, uname=unicode_name(char))
    data, meta = await llm.vision_json(prompt, base64.b64encode(jpeg).decode())
    return parse_grade(data, char, lang), meta


def unicode_name(char: str) -> str:
    """e.g. 'HEBREW LETTER SHIN': anchors the model on look-alikes (ש vs ע)."""
    names = []
    for c in char:
        try:
            names.append(unicodedata.name(c).lower())
        except ValueError:
            pass
    return " + ".join(names) or "character"

