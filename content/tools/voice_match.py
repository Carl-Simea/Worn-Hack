"""Reference voice matcher for content/voice/commands.json (agent C). Small and dependency-free so it ports to JS (D)
and can be imported by the backend's POST /voice (A).

    from voice_match import match
    match("write my name, Maria", screen="home")
    → {"heard": "write my name, Maria", "intent": "write_name", "args": {"name": "Maria"},
       "say": "Maria. Pick a script, or say a language.", "nav": "name"}

    python3 content/tools/voice_match.py --test             # every case in content/voice/tests.json
    python3 content/tools/voice_match.py lesson "i'm done"  # one utterance

Algorithm (keep the JS port identical):
 1. normalize: lowercase, curly quotes → ', keep [a-z0-9' ], digits 0-5 → words, collapse spaces.
 2. strip leading fillers (repeatedly, longest first) and a trailing "please".
 3. for each intent in order (skipping intents whose "screens" excludes the current screen, but remembering them):
    whole utterance == one of its phrases → match. Then the same pass over templates (slots: {language} {word}
    {screen} are alias alternations; {name} 1-3 words; {text} 1-12 words).
 4. fuzzy: if <= max_words words, the best difflib ratio >= min_ratio over every phrase and every slot-free expansion
    of a template (language/word/screen aliases filled in).
 5. "learn <something unknown>" → intent null, args {"reason": "unknown_language"} with the language list.
 6. a match only allowed on other screens → intent null, args {"reason": "not_here"}; nothing → intent null.
"""
import difflib
import json
import re
import sys
from pathlib import Path

VOICE = Path(__file__).resolve().parent.parent / "voice"
_cfg = None


def cfg():
    global _cfg
    if _cfg is None:
        _cfg = json.loads((VOICE / "commands.json").read_text(encoding="utf-8"))
        _cfg["_screens"] = json.loads((VOICE / "screens.json").read_text(encoding="utf-8"))["screens"]
        _cfg["_compiled"] = [(it, [_compile(t) for t in it.get("templates", [])]) for it in _cfg["intents"]]
        _cfg["_fuzzy"] = _fuzzy_candidates()
    return _cfg


def normalize(text):
    c = cfg()
    t = (text or "").lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = " ".join(c["numbers"].get(w, w) for w in t.split())
    t = re.sub(r"(^| )'+|'+( |$)", " ", t)
    t = " ".join(t.split())
    changed = True
    while changed and t:
        changed = False
        for f in c["fillers"]:
            if t == f:
                return ""
            if t.startswith(f + " "):
                t = t[len(f) + 1:]
                changed = True
                break
    if t.endswith(" please"):
        t = t[:-7]
    return t




def _compile(tpl):
    al = _cfg["aliases"]
    slots = []
    def rep(m):
        name = m.group(1)
        slots.append(name)
        if name in al:
            pairs = sorted(((a, k) for k, v in al[name].items() for a in v), key=lambda p: -len(p[0]))
            return "(" + "|".join(re.escape(a) for a, _ in pairs) + ")"
        if name == "name":
            return r"([a-z']+(?: [a-z']+){0,2})"
        return r"([a-z0-9']+(?: [a-z0-9']+){0,11})"
    rx = re.sub(r"\\\{(\w+)\\\}", rep, re.escape(tpl))
    return re.compile("^" + rx + "$"), slots


def _resolve(kind, alias):
    for k, v in cfg()["aliases"][kind].items():
        if alias in v:
            return k
    return None


def _fuzzy_candidates():
    al = _cfg["aliases"]
    out = []
    for it in _cfg["intents"]:
        for p in it.get("phrases", []):
            out.append((p, it, {}))
        for t in it.get("templates", []):
            slots = re.findall(r"\{(\w+)\}", t)
            if len(slots) != 1 or slots[0] not in al:
                continue
            kind = slots[0]
            for k, v in al[kind].items():
                for a in v:
                    out.append((t.replace("{" + kind + "}", a), it, {kind: k}))
    return out


def _allowed(it, screen):
    return not it.get("screens") or screen is None or screen in it["screens"]


def _fill(s, args, screen):
    c = cfg()
    if not s:
        return s
    sub = {}
    if "language" in args:
        sub["language"] = c["language_names"][args["language"]]
    if "word" in args:
        sub["word"] = c["word_names"][args["word"]]
    if "screen" in args:
        sub["screen"] = args["screen"]
        sub["screen_title"] = c["screen_titles"][args["screen"]]
    for k in ("name", "text"):
        if k in args:
            sub[k] = args[k]
    sugg = c["_screens"].get(screen or "home", {}).get("suggestions", [])
    sub["suggestions"] = ", ".join(sugg)
    return re.sub(r"\{(\w+)\}", lambda m: sub.get(m.group(1), m.group(0)), s)


def _result(heard, it, args, screen):
    nav = it.get("nav")
    if nav == "{screen}":
        nav = args.get("screen")
    return {"heard": heard, "intent": it["id"], "args": args, "say": _fill(it.get("say", ""), args, screen), "nav": nav}


def match(heard, screen=None):
    c = cfg()
    t = normalize(heard)
    hint = c["_screens"].get(screen or "home", {}).get("hint", "")
    none = {"heard": heard, "intent": None, "args": {}, "say": c["not_understood"][0], "nav": None, "hint": hint}
    if not t:
        return none
    blocked = None
    for it in c["intents"]:
        if t in it.get("phrases", []):
            if _allowed(it, screen):
                return _result(heard, it, {}, screen)
            blocked = blocked or it
    for it, comp in c["_compiled"]:
        for rx, slots in comp:
            m = rx.match(t)
            if not m:
                continue
            args = {}
            for slot, val in zip(slots, m.groups()):
                if slot in c["aliases"]:
                    args[slot] = _resolve(slot, val)
                elif slot == "name":
                    args[slot] = val.title()
                else:
                    args[slot] = val
            if _allowed(it, screen):
                return _result(heard, it, args, screen)
            blocked = blocked or it
            break
    if blocked is None and len(t.split()) <= c["fuzzy"]["max_words"]:
        best, score = None, c["fuzzy"]["min_ratio"]
        for cand, it, args in c["_fuzzy"]:
            if not _allowed(it, screen):
                continue
            r = difflib.SequenceMatcher(None, t, cand).ratio()
            if r > score:
                best, score = (it, args), r
        if best:
            return _result(heard, best[0], dict(best[1]), screen)
    if blocked is None and any(t.startswith(w + " ") for w in c["unknown_language"]["starts"]):
        return {**none, "args": {"reason": "unknown_language"}, "say": c["unknown_language"]["say"]}
    if blocked is not None:
        return {**none, "args": {"reason": "not_here", "wanted": blocked["id"]}, "say": c["not_here"]}
    return none


def run_tests(verbose=True):
    global _cfg
    _cfg = None
    cases = json.loads((VOICE / "tests.json").read_text(encoding="utf-8"))["cases"]
    fails = 0
    for cse in cases:
        r = match(cse["heard"], cse["screen"])
        ok = r["intent"] == cse["intent"] and (cse["intent"] is None or r["args"] == cse["args"])
        if not ok:
            fails += 1
            if verbose:
                print(f"FAIL [{cse['screen']}] {cse['heard']!r}: want {cse['intent']} {cse['args']}, "
                      f"got {r['intent']} {r['args']}")
    return fails


if __name__ == "__main__":
    if sys.argv[1:2] == ["--test"]:
        n = run_tests()
        print(f"{n} failing")
        sys.exit(1 if n else 0)
    screen, *words = sys.argv[1:] or ["home", "help"]
    print(json.dumps(match(" ".join(words), screen), ensure_ascii=False, indent=1))
