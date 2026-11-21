"""Tier 3 perception: qwen2.5vl:7b reads the handwriting and we compare its reading to the target."""

from __future__ import annotations

import base64
import io

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
Step 2: The learner (an English-speaking beginner) was TRYING to write "{char}". Compare what you read with "{char}".

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


def parse_grade(data: dict, char: str) -> dict:
    seen = str(data.get("seen") or "").strip()
    score = int(max(0, min(100, float(data.get("score") or 0))))
    fix = str(data.get("fix") or "").strip().splitlines()[0][:120] if data.get("fix") else ""
    if not seen and char in fix:
        seen = char  # the model named the char in its fix but left "seen" blank
    if not seen:
        return {"correct": False, "score": 0, "seen": "",
                "feedback": "I can't see your writing, hold the paper closer."}
    # The model's reading decides "correct"; its score alone is too generous.
    correct = char in seen and score >= 60
    if not correct:
        score = min(score, 45)
        if not fix:
            fix = f"That looks like {seen}, not {char}. Watch the animation again."
    feedback = (f"Nice! That's {char}." if score >= 85 else f"Good, {char} is readable.") if correct else fix
    return {"correct": correct, "score": score, "seen": seen, "feedback": feedback}


async def grade(jpeg: bytes, char: str, lang: str) -> tuple[dict, dict]:
    """Returns (result, meta). Raises llm.LLMError / asyncio.TimeoutError when the model is unavailable."""
    prompt = PROMPT.format(lang_name=LANG_NAMES.get(lang, lang), char=char)
    data, meta = await llm.vision_json(prompt, base64.b64encode(jpeg).decode())
    return parse_grade(data, char), meta

