"""Tier 3 perception: qwen2.5vl:7b reads the handwriting and we compare its reading to the target."""

from __future__ import annotations

import base64
import io
import re
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


def _unlatex(seen: str) -> str:
    """The model sometimes answers Greek in LaTeX ('\\lambda'). Map \\name back to the letter."""
    def sub(m):
        name = m.group(1)
        case = "CAPITAL" if name[0].isupper() else "SMALL"
        name = {"lambda": "lamda", "varsigma": "final sigma"}.get(name.lower(), name)  # Unicode spellings
        try:
            return unicodedata.lookup(f"GREEK {case} LETTER {name.upper()}")
        except KeyError:
            return m.group(0)
    return re.sub(r"\\([A-Za-z]+)", sub, seen)


def parse_grade(data: dict, char: str, lang: str = "") -> dict:
    seen = _unlatex(str(data.get("seen") or "").strip())
    score = int(max(0, min(100, float(data.get("score") or 0))))
    model_score = score
    fix = str(data.get("fix") or "").strip().splitlines()[0][:120] if data.get("fix") else ""
    if not seen and char in fix:
        seen = char  # the model named the char in its fix but left "seen" blank
    if not seen:
        return {"correct": False, "score": 0, "seen": "", "model_score": model_score, "exact_read": False,
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
    return {"correct": correct, "score": score, "seen": seen, "feedback": feedback, "model_score": model_score,
            "exact_read": bool(seen) and char in seen}


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



# ------------------------------------------------------------------ rubric (measured grading, worn/grading.py)

RUBRIC_PROMPT = """This image has two panels. LEFT: a beginner's handwriting (photo, cropped). RIGHT: the target in print: {lang_name}, {script} script, "{char}" ({uname}){rom}.
Rate the LEFT handwriting as an attempt at the RIGHT character. Personal style (print vs cursive, slant, line thickness) is never a fault.

Reply with JSON only:
{{"seen": "the character you read on the LEFT", "rec": 0-10, "prop": 0-10, "place": 0-10, "comp": 0-10, "neat": 0-10, "fix": "ONE fix, max 7 words, or empty"}}

rec = recognizable as {char} (0-2 if it is a different character or unreadable). prop = proportions. place = parts in the right places relative to each other. comp = all strokes/parts present. neat = clean lines."""

RUBRIC_KEYS = ("recognizable", "proportions", "stroke_placement", "completeness", "neatness")


def _rubric_validator(d: dict) -> dict:
    out = {}
    short = {"recognizable": "rec", "proportions": "prop", "stroke_placement": "place", "completeness": "comp",
             "neatness": "neat"}
    for k in RUBRIC_KEYS:
        v = d.get(short[k], d.get(k))
        out[k] = int(round(max(0.0, min(10.0, float(v)))))
    out["seen"] = _unlatex(str(d.get("seen") or "").strip())[:8]
    fix = str(d.get("fix") or "").strip()
    out["fix"] = fix.splitlines()[0][:120] if fix else ""
    return out


SCRIPTS = {"mandarin": "Simplified Chinese (hanzi)", "hindi": "Devanagari", "arabic": "Arabic (isolated form)",
           "russian": "Cyrillic", "hebrew": "Hebrew (block print)", "greek": "Greek", "latin": "Latin"}


async def rubric(image_jpeg: bytes, char: str, lang: str, romanization: str | None = None) -> tuple[dict, dict]:
    """qwen2.5vl scores the cropped writing next to the reference → ({5 sub-scores 0-10, seen, fix}, meta)."""
    import time
    t0 = time.perf_counter()
    prompt = RUBRIC_PROMPT.format(lang_name=LANG_NAMES.get(lang, lang).split(" (")[0], script=SCRIPTS.get(lang, lang),
                                  char=char, uname=unicode_name(char),
                                  rom=f', pronounced "{romanization}"' if romanization else "")
    data = await llm.json_call(llm.config.VISION_MODEL, prompt, images=[base64.b64encode(image_jpeg).decode()],
                               timeout=llm.config.GRADE_TIMEOUT, validate=_rubric_validator, temperature=0.1,
                               num_predict=70)
    return data, {"model": llm.config.VISION_MODEL, "ms": int((time.perf_counter() - t0) * 1000)}
