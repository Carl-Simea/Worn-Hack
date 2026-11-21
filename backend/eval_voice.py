"""Live NLU eval: 45+ real-world phrasings through POST /voice (text) with the real qwen2.5:7b.

uv run python eval_voice.py [--port 8000]   → prints accuracy + latency, writes test_data/voice_eval.md
Each case: (screen, heard, expected intents in order, optional args check). A lesson is opened first when the
case needs one (screen "lesson").
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

CASES: list[tuple[str, str, list[str], dict]] = [
    # navigation
    ("lesson", "take me back home", ["home"], {}),
    ("words", "go back", ["back"], {}),
    ("words", "uh, back please", ["back"], {}),
    ("learn", "can we go to the home screen", ["home"], {}),
    ("home", "open my journal", ["open"], {"screen": "journal"}),
    ("home", "show me the daily five", ["open"], {"screen": "daily5"}),
    ("home", "how does this thing work", ["open|help"], {}),
    ("home", "go home then open the journal", ["home", "open"], {}),
    ("home", "let's exit", ["exit"], {}),
    ("lesson", "ok bye scribi", ["exit"], {}),
    ("home", "I'm done for today", ["exit"], {}),
    ("home", "close the app", ["exit"], {}),
    # learning
    ("home", "teach me something in Arabic", ["learn"], {"lang": "arabic"}),
    ("home", "I wanna learn some greek", ["learn"], {"lang": "greek"}),
    ("home", "let's do hindi", ["learn"], {"lang": "hindi"}),
    ("learn", "um the russian one", ["learn"], {"lang": "russian"}),
    ("home", "teach me water in hebrew", ["select"], {"lang": "hebrew", "item_id": "water"}),
    ("words", "let's do thank you", ["select"], {"item_id": "thank_you"}),
    ("home", "how do you say hello in Mandarin", ["select"], {"lang": "mandarin", "item_id": "hello"}),
    ("home", "I want to spell water in Hebrew", ["select"], {"lang": "hebrew", "item_id": "water"}),
    ("home", "how do I write friend in greek", ["select"], {"lang": "greek", "item_id": "friend"}),
    # lesson controls
    ("lesson", "that was too fast", ["slower"], {}),
    ("lesson", "whoa slow down", ["slower"], {}),
    ("lesson", "can you speed it up", ["faster"], {}),
    ("lesson", "skip this one, it's too hard", ["skip"], {}),
    ("lesson", "say that again", ["repeat"], {}),
    ("lesson", "wait what did you say", ["repeat"], {}),
    ("lesson", "show me the strokes again", ["show_again"], {}),
    ("lesson", "ok I think I'm finished", ["check"], {}),
    ("lesson", "how did I do", ["check"], {}),
    ("lesson", "can you check it", ["check"], {}),
    ("lesson", "what does this mean", ["meaning"], {}),
    ("lesson", "what am I even writing", ["meaning"], {}),
    ("lesson", "go to the next one", ["next"], {}),
    ("lesson", "move on", ["next"], {}),
    ("lesson", "go back one", ["previous|back"], {}),
    # compose + names
    ("home", "how do I write good morning in greek", ["compose"], {"lang": "greek"}),
    ("home", "help me write see you tomorrow in russian", ["compose"], {"lang": "russian"}),
    ("home", "write my name, Maria", ["write_name"], {"name": "Maria"}),
    ("home", "can you write my name? it's Jordan", ["write_name"], {"name": "Jordan"}),
    ("home", "how do you write my name", ["ask"], {}),
    # help + chatter
    ("home", "what can I say", ["help"], {}),
    ("lesson", "I'm stuck, help", ["help"], {}),
    ("home", "yeah so the meeting got moved to three", ["unknown"], {}),
    ("lesson", "did you see the game last night", ["unknown"], {}),
    # one-word fast path
    ("lesson", "next", ["next"], {}),
    ("words", "back", ["back"], {}),
    ("lesson", "check", ["check"], {}),
    ("home", "home", ["home"], {}),
]


def run(port: int) -> dict:
    base = f"http://localhost:{port}"
    c = httpx.Client(base_url=base, timeout=30)
    rows, ok_n = [], 0
    for screen, heard, want, chk in CASES:
        c.post("/reset")
        if screen == "lesson":
            c.post("/voice", data={"text": "learn mandarin", "screen": "home"})
            c.post("/voice", data={"text": "water", "screen": "words"})
            c.post("/app-state", json={"screen": "lesson", "phase": "result"})
        elif screen == "words":
            c.post("/voice", data={"text": "learn mandarin", "screen": "home"})
        c.post("/app-state", json={"screen": screen})
        t = time.perf_counter()
        d = c.post("/voice", data={"text": heard, "screen": screen}).json()
        ms = (time.perf_counter() - t) * 1000
        got = [s["intent"] for s in d.get("steps") or []] or [d.get("intent")]
        if d.get("intent") == "ask":
            got = ["ask"]
        good = len(got) == len(want) and all(g in w.split("|") for g, w in zip(got, want))
        if good and chk:
            a = {**(d.get("args") or {}), **((d.get("nav") or {}) if "screen" in chk else {})}
            for k, v in chk.items():
                av = (d.get("session") or {}).get(k) if k in ("item_id",) and d.get("session") else a.get(k)
                if k == "lang" and d.get("session"):
                    av = d["session"]["lang"]
                if str(av).lower() != str(v).lower():
                    good = False
        ok_n += good
        rows.append({"screen": screen, "heard": heard, "want": want, "got": got, "ok": good, "via": d.get("matcher"),
                     "ms": round(ms), "say": (d.get("say") or "")[:80]})
        print(f"{'OK ' if good else 'BAD'} {ms:6.0f}ms {d.get('matcher'):7} [{screen}] {heard!r} → {got}  {('' if good else 'want ' + str(want))}")
    model_ms = [r["ms"] for r in rows if r["via"] == "model"]
    fast_ms = [r["ms"] for r in rows if r["via"] == "fast"]
    out = {"n": len(rows), "correct": ok_n, "accuracy": round(ok_n / len(rows), 3),
           "model_ms": {"avg": round(statistics.mean(model_ms)) if model_ms else None,
                        "p90": round(sorted(model_ms)[int(0.9 * len(model_ms)) - 1]) if model_ms else None},
           "fast_ms": {"avg": round(statistics.mean(fast_ms)) if fast_ms else None},
           "fallbacks": sum(1 for r in rows if r["via"] == "rules"), "rows": rows}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    res = run(ap.parse_args().port)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}))
    md = [f"# Voice NLU eval (qwen2.5:7b, text in)\n", f"**{res['correct']}/{res['n']}** correct "
          f"({res['accuracy']:.0%}). Model path avg {res['model_ms']['avg']} ms (p90 {res['model_ms']['p90']}), "
          f"one-word fast path avg {res['fast_ms']['avg']} ms, rule fallbacks {res['fallbacks']}.\n",
          "| ok | screen | heard | got | via | ms |", "|---|---|---|---|---|---|"]
    md += [f"| {'✓' if r['ok'] else '✗'} | {r['screen']} | {r['heard']} | {', '.join(map(str, r['got']))} | {r['via']} | {r['ms']} |"
           for r in res["rows"]]
    Path(__file__).parent.joinpath("test_data", "voice_eval.md").write_text("\n".join(md) + "\n")
