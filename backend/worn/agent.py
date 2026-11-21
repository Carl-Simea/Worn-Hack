"""The Worn tutor agent: observe -> evaluate -> decide -> act, with real tools.

Every step (and every tool call) is logged with its latency into LIVE.agent_steps, so the
/live page can show judges the agent thinking in real time.

Tools
  grade_character     tier-3 vision read of the photo (qwen2.5vl:7b)
  compare_to_template OpenCV whole-character similarity to the stroke template (tier-2 machinery)
  choose_next_item    adaptive next step from the per-user mistake memory
  compose_message     translate the learner's own message into writable units (qwen2.5:14b)
  react               the short spoken/displayed reaction + mood for the glasses

The DECIDE step is the LLM (qwen2.5:14b, 3 s budget, then qwen2.5:7b): it sees the observation,
both evaluations and the memory, and picks the action + reaction as strict JSON. Code-side
guardrails keep it honest (it can't advance a char the vision model rejected before 3 tries,
and can't send a correct answer back for a retry). If both models fail, a rule-based policy
decides, and that's logged too."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Any, Awaitable, Callable

from . import compose as compose_mod
from . import config, llm, memory, scripts, strokes, vision
from .live import LIVE

log = logging.getLogger("worn.agent")
_run_ids = itertools.count(1)

MOODS = ("celebrate", "proud", "encourage", "gentle")
ECHO_MODEL_SCORE = 60     # below this the vision read is weak...
ECHO_TEMPLATE_SCORE = 40  # ...and needs at least this template agreement to count
ARBITRATE_MIN = 65        # target template score needed before tier 2 may overturn a vision misread
ARBITRATE_MARGIN = 15     # ...and it must beat the template of the letter vision named by this much
SYMBOL_TEMPLATE_SCORE = 75  # vision read a non-letter symbol: only a strong template match counts
ACTIONS = ("advance", "retry", "review")
HARSH = ("bad", "wrong", "ugly", "messy", "sloppy", "poor", "terrible", "awful", "fail", "stupid", "careless")

TOOLS: dict[str, dict[str, Any]] = {
    "grade_character": {"desc": "Read the handwriting photo with the vision model and compare it to the target."},
    "compare_to_template": {"desc": "OpenCV similarity between the ink and the character's stroke template."},
    "choose_next_item": {"desc": "Pick the next character/item from the learner's mistake memory."},
    "compose_message": {"desc": "Translate the learner's own short message into characters to write."},
    "react": {"desc": "Say a short, kind reaction on the glasses."},
}


def tool_catalog() -> list[dict]:
    return [{"name": k, "description": v["desc"]} for k, v in TOOLS.items()]


class Run:
    """One agent run; wraps each step with timing + logging."""

    def __init__(self, goal: str):
        self.id = f"r{next(_run_ids)}"
        self.goal = goal
        self.t0 = time.perf_counter()
        self.steps: list[dict] = []

    def step(self, phase: str, summary: str, **kw) -> dict:
        s = LIVE.add_step(self.id, phase, summary, **kw)
        self.steps.append(s)
        return s

    async def tool(self, phase: str, name: str, fn: Callable[[], Awaitable[Any]], summarize: Callable[[Any], str]):
        t = time.perf_counter()
        try:
            out = await fn()
        except Exception as e:
            ms = (time.perf_counter() - t) * 1000
            self.step(phase, f"{name} failed: {str(e)[:120]}", tool=name, ms=ms, status="error")
            raise
        ms = (time.perf_counter() - t) * 1000
        data, meta = out if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], dict) else (out, {})
        self.step(phase, summarize(data), tool=name, ms=ms, data=_slim(data), model=meta.get("model"))
        return data, meta, ms

    def total_ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)


def _slim(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: v for k, v in d.items() if k not in ("stats",) and not isinstance(v, (bytes, bytearray))}
    return d


# ------------------------------------------------------------------ react

def kind(text: str, fallback: str) -> str:
    """Feedback is never harsh and never about personal style."""
    t = (text or "").strip()
    if not t or any(w in t.lower().split() or f"{w}." in t.lower() or f"{w}," in t.lower() for w in HARSH):
        return fallback
    return t[:90]


_RETRY_WORDS = ("try again", "again", "almost", "close", "one more", "not quite", "keep trying")
_WIN_WORDS = ("nailed", "great job", "perfect", "got it", "well done", "you did it", "beautiful", "excellent")


def react(mood: str, line: str, correct: bool) -> dict:
    """The spoken line and mood must agree with the verdict (the LLM sometimes says
    'try again' on a correct answer, or 'nailed it' on a miss)."""
    low = (line or "").lower()
    if correct and (mood not in ("celebrate", "proud") or any(w in low for w in _RETRY_WORDS)):
        mood, line = ("proud" if mood == "proud" else "celebrate"), (line if not any(w in low for w in _RETRY_WORDS) else "")
    elif not correct and (mood in ("celebrate", "proud") or any(w in low for w in _WIN_WORDS)):
        mood, line = "encourage", (line if not any(w in low for w in _WIN_WORDS) else "")
    mood = mood if mood in MOODS else ("celebrate" if correct else "encourage")
    default = {"celebrate": "Beautiful, you got it!", "proud": "Yes! Nicely done.",
               "encourage": "So close, one more try!", "gentle": "Let's watch it once more together."}[mood]
    emoji = {"celebrate": "🎉", "proud": "✨", "encourage": "💪", "gentle": "👀"}[mood]
    sound = "success" if correct else "retry"
    return {"reaction": kind(line, default), "mood": mood, "emoji": emoji, "sound": sound}


# ------------------------------------------------------------------ decide

DECIDE_SYSTEM = ("You are Scribi, the warm, playful handwriting tutor in the Worn smart-glasses app, for English speakers learning "
                 "non-Latin scripts. You never criticize personal handwriting style (slant, size, print vs cursive). "
                 "You keep learning fun and never a chore. Answer with one JSON object only.")

DECIDE_PROMPT = """Decide the next move after the learner wrote one character on paper.

Target: "{char}" ({lang_name}), item "{meaning}" (char {pos} of {total}).
Vision read (tier 3): saw "{seen}", score {score}/100, correct={correct}. Fix suggested: "{fix}".
Template match (tier 2, OpenCV): {tmpl}/100.
Memory for this character: {mem}. Misses in a row right now: {tries}.
Weakest characters in this language: {weak}.

Actions:
- "advance": move on (use when correct; or after 3+ misses so it stays fun, the memory will bring it back later).
- "retry": same character again (use when not correct and misses < 3).
- "review": jump to a weak character from memory (use rarely, when correct AND a weak char exists).

JSON only:
{{"why": "max 5 words", "action": "advance|retry|review", "mood": "celebrate|proud|encourage|gentle", "say": "max 6 words, spoken aloud, kind"}}"""


def _decide_validator(d: dict) -> dict:
    action = str(d.get("action", "")).strip().lower()
    if action not in ACTIONS:
        raise ValueError(f"bad action {action!r}")
    mood = str(d.get("mood", "")).strip().lower()
    reaction = str(d.get("say") or d.get("reaction") or "").strip()
    if not reaction:
        raise ValueError("missing say")
    return {"thought": str(d.get("why") or d.get("thought") or "").strip()[:120], "action": action,
            "mood": mood if mood in MOODS else "", "reaction": reaction[:90]}


def rule_policy(correct: bool, tries_after: int, weak_exists: bool) -> dict:
    if correct:
        return {"thought": "Correct, so move on.", "action": "advance", "mood": "celebrate", "reaction": "Nailed it!"}
    if tries_after >= 3:
        return {"thought": "Three misses; move on and let memory bring it back.", "action": "advance",
                "mood": "gentle", "reaction": "Let's come back to this one later."}
    return {"thought": "Not yet; try again with the fix.", "action": "retry", "mood": "encourage",
            "reaction": "Almost! Try once more."}


def guardrails(dec: dict, correct: bool, tries_after: int) -> tuple[dict, str | None]:
    if not correct and dec["action"] in ("advance", "review") and tries_after < 3:
        return {**dec, "action": "retry"}, "vision says not yet and fewer than 3 tries: retry"
    if correct and dec["action"] == "retry":
        return {**dec, "action": "advance"}, "correct answers move forward"
    return dec, None


# ------------------------------------------------------------------ grade run

async def run_grade(jpeg: bytes, char: str, lang: str, session: dict | None, image_url: str | None,
                    user: str = memory.DEFAULT_USER, progress=None) -> dict:
    """The full loop for one handwriting photo. Returns the /grade response body."""
    run = Run(f"grade {char}")
    sess_match = bool(session and session.get("char") == char and session.get("lang") == lang)
    item_id = session.get("item_id") if sess_match else None
    char_index = int(session.get("char_index", 0)) if sess_match else 0
    meaning = (session or {}).get("meaning") if sess_match else None
    total = (session or {}).get("total_chars", 1) if sess_match else 1
    mem = memory.char_stats(lang, char, user)

    # OBSERVE
    lang_name = config.LANGS.get(lang, {}).get("name", lang)
    run.step("observe", f"Photo of {char} ({lang_name})" + (f", item {meaning}" if meaning else "")
             + (f"; memory: {mem.get('attempts', 0)} tries, {mem.get('fails', 0)} misses" if mem else "; first try ever"),
             data={"char": char, "lang": lang, "item_id": item_id, "char_index": char_index,
                   "image_url": image_url, "memory": {k: mem.get(k) for k in ("attempts", "fails", "streak")}})

    # EVALUATE: vision (tier 3) and template (tier 2 machinery) in parallel
    async def _vision():
        try:
            return await vision.grade(jpeg, char, lang)
        except Exception:
            if config.FAKE_GRADE:
                return {"correct": True, "score": 80, "seen": char, "feedback": "Nice work, keep going!"}, \
                       {"model": "fake (WORN_FAKE_GRADE=1)"}
            raise

    async def _template():
        return await asyncio.to_thread(strokes.compare_full, jpeg, lang, char)

    vis_task = run.tool("evaluate", "grade_character", _vision,
                        lambda r: f"Vision read \"{r.get('seen') or '?'}\": {r['score']}/100, "
                                  f"{'correct' if r['correct'] else 'not yet'}")
    tmp_task = run.tool("evaluate", "compare_to_template", _template,
                        lambda r: f"Template match {r['score']}/100 ({r['template']})")
    vis_res, tmp_res = await asyncio.gather(vis_task, tmp_task, return_exceptions=True)
    if isinstance(vis_res, BaseException):
        raise vis_res  # /grade turns this into a friendly 503
    graded, vmeta, vision_ms = vis_res
    template_score = None if isinstance(tmp_res, BaseException) else tmp_res[0]["score"]
    LIVE.latency("tier3", vision_ms)

    # Echo guard: a vision model told the target can "read" it in anything (a big X read as 你).
    # A weak read (model's own score < 60) only counts when the stroke template agrees.
    if (graded["correct"] and graded.get("model_score", 100) < ECHO_MODEL_SCORE and template_score is not None
            and template_score < ECHO_TEMPLATE_SCORE):
        graded = {**graded, "correct": False, "score": min(graded["score"], 40),
                  "feedback": f"Hmm, I'm not sure that's {char} yet. Watch the strokes, then try again."}
        run.step("evaluate", f"Echo guard: vision only {graded.get('model_score')}/100 and template {template_score}/100, "
                             f"so not counted", data={"guard": "echo"})
    # Template arbitration: vision models confuse look-alike letters in less common scripts (qwen2.5vl
    # reads ש as ע). When vision names a different single letter but the target's stroke template
    # matches strongly, compare the photo against BOTH templates; a clear win for the target overturns it.
    seen = graded.get("seen") or ""
    same_script_letter = len(seen) == 1 and seen != char and lang in scripts._RANGES and scripts.in_script(seen, lang)
    if (not graded["correct"] and same_script_letter and template_score is not None
            and template_score >= ARBITRATE_MIN):
        t_arb = time.perf_counter()
        try:
            other = (await asyncio.to_thread(strokes.compare_full, jpeg, lang, seen))["score"]
        except Exception:
            other = None
        if other is not None and template_score - other >= ARBITRATE_MARGIN:
            graded = {**graded, "correct": True, "score": max(min(template_score, 80), 65), "seen": char,
                      "vision_seen": seen, "feedback": f"Got it, that's {char}!", "arbitrated": True}
        run.step("evaluate", f"Template arbitration {char} vs {seen}: {template_score} vs {other}"
                             + (" -> counts as " + char if graded.get("arbitrated") else " -> vision stands"),
                 tool="compare_to_template", ms=(time.perf_counter() - t_arb) * 1000,
                 data={"target": template_score, "seen": other, "overturned": bool(graded.get("arbitrated"))})
    # Vision answered with a symbol, not a letter ('\\' for a slanted λ): no letter to compare against,
    # so only a very strong stroke-template match counts.
    if (not graded["correct"] and len(seen) == 1 and not seen.isalpha() and template_score is not None
            and template_score >= SYMBOL_TEMPLATE_SCORE):
        graded = {**graded, "correct": True, "score": max(min(template_score, 80), 65), "seen": char,
                  "vision_seen": seen, "feedback": f"Got it, that's {char}!", "arbitrated": True}
        run.step("evaluate", f"Vision saw only a symbol ({seen}); template {template_score}/100 says {char}",
                 data={"guard": "symbol", "template": template_score})
    correct = bool(graded["correct"])
    tries_after = 0 if correct else LIVE.tries + 1
    weak = sorted(((memory.weakness(st), c) for c, st in memory.lang_stats(lang, user).items()
                   if c != char and memory.weakness(st) > 0.3), reverse=True)[:3]

    # DECIDE (LLM, with fallback + rules)
    prompt = DECIDE_PROMPT.format(
        char=char, lang_name=config.LANGS.get(lang, {}).get("name", lang), meaning=meaning or "practice",
        pos=char_index + 1, total=total, seen=graded.get("seen") or "nothing", score=graded["score"],
        correct=str(correct).lower(), fix=graded.get("feedback", "") if not correct else "",
        tmpl=template_score if template_score is not None else "n/a",
        mem=(f"{mem.get('attempts', 0)} tries, {mem.get('fails', 0)} misses" if mem else "never tried before"),
        tries=tries_after, weak=", ".join(c for _, c in weak) or "none")
    t = time.perf_counter()
    try:
        dec, dmeta = await llm.tutor_json(prompt, system=DECIDE_SYSTEM, validate=_decide_validator,
                                          num_predict=48, temperature=0.5)
        via = dmeta["model"] + (" (fallback: " + dmeta.get("reason", "") + ")" if dmeta.get("fallback") else "")
    except llm.LLMError as e:
        dec, dmeta, via = rule_policy(correct, tries_after, bool(weak)), {"model": "rules"}, f"rules ({e})"
    decide_ms = (time.perf_counter() - t) * 1000
    LIVE.latency("decide", decide_ms)
    dec, guard = guardrails(dec, correct, tries_after)
    run.step("decide", f"{dec['action'].upper()}: {dec['thought'] or 'decided'}" + (f" [guardrail: {guard}]" if guard else ""),
             ms=decide_ms, model=via, data={"action": dec["action"], "mood": dec["mood"], "guardrail": guard,
                                            "fallback": dmeta.get("fallback", False)})

    # ACT: choose_next_item + react
    async def _next():
        if not item_id:
            return {"action": dec["action"], "reason": "no active lesson for this char"}
        return memory.choose_next(lang, item_id, char_index, dec["action"], user)

    nxt, _, _ = await run.tool("act", "choose_next_item", _next,
                               lambda n: f"Next: {n.get('char') or '-'} ({n.get('reason')})")

    async def _react():
        return react(dec["mood"], dec["reaction"], correct)

    rx, _, _ = await run.tool("act", "react", _react, lambda r: f"{r['emoji']} \"{r['reaction']}\"")

    feedback = graded["feedback"] if not correct else kind(graded["feedback"], f"Nice! That's {char}.")
    result = {
        "correct": correct,
        "score": graded["score"],
        "feedback": kind(feedback, "Close! Watch the animation once more."),
        "reaction": rx["reaction"],
        "mood": rx["mood"],
        "emoji": rx["emoji"],
        "sound": rx["sound"],
        "seen": graded.get("seen", ""),
        "template_score": template_score,
        "char": char,
        "lang": lang,
        "item_id": item_id,
        "char_index": char_index,
        "image_url": image_url,
        "next": nxt if item_id else None,
        "tries": tries_after,
        "agent": {"run_id": run.id, "decided_by": dmeta.get("model"), "fallback": dmeta.get("fallback", False),
                  "thought": dec["thought"], "action": dec["action"], "steps": len(run.steps) + 1},
        "latency_ms": run.total_ms(),
        "tier3_ms": int(vision_ms),
        "ts": time.time(),
    }
    memory.record_attempt({"lang": lang, "item_id": item_id, "char_index": char_index, "char": char,
                           "score": result["score"], "correct": correct, "feedback": result["feedback"],
                           "seen": result["seen"], "image_url": image_url,
                           "mode": (session or {}).get("mode", "write")}, user)
    LIVE.latency("grade", result["latency_ms"])
    run.step("act", f"Done in {result['latency_ms']} ms", ms=result["latency_ms"])
    return result


# ------------------------------------------------------------------ compose run

async def run_compose(text: str, lang: str) -> dict:
    run = Run(f"compose {lang}")
    run.step("observe", f"Learner wants to write \"{text[:60]}\" in {config.LANGS.get(lang, {}).get('name', lang)}")
    out, meta, _ = await run.tool("act", "compose_message", lambda: compose_mod.compose_message(text, lang),
                                  lambda r: f"{r['native']} ({r['romanization']}), {len(r['chars'])} to write; "
                                            + (f"checked: reads back as \"{r.get('check')}\"" if r.get("verified")
                                               else "not checked"))
    return {**out, "model": meta.get("model"), "fallback": meta.get("fallback", False), "run_id": run.id}
