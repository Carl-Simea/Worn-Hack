"""Per-user mistake memory + practice journal, persisted to backend/data/.

memory.json : {user: {lang: {char: {attempts, correct, fails, streak, last_ts, last_score, last_correct_ts,
                                    fixes: [last 3 fixes], item_id, char_index}}}}
journal.jsonl: one graded attempt per line.

choose_next() and daily5() are the adaptive parts the tutor agent calls as tools."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from . import config, content

_lock = threading.RLock()
DEFAULT_USER = "demo"


def _mem_path():
    return config.DATA_DIR / "memory.json"


def _journal_path():
    return config.DATA_DIR / "journal.jsonl"


def _load() -> dict:
    try:
        return json.loads(_mem_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(mem: dict) -> None:
    tmp = _mem_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(mem, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _mem_path())


def record_attempt(entry: dict, user: str = DEFAULT_USER) -> dict:
    """entry: {lang, item_id, char_index, char, score, correct, feedback, seen, image_url, mode}.
    Updates memory and appends to the journal. Returns the char's updated stats."""
    now = time.time()
    with _lock:
        mem = _load()
        st = mem.setdefault(user, {}).setdefault(entry["lang"], {}).setdefault(entry["char"], {
            "attempts": 0, "correct": 0, "fails": 0, "streak": 0, "fixes": []})
        st["attempts"] += 1
        st["last_ts"] = now
        st["last_score"] = entry.get("score")
        st["item_id"] = entry.get("item_id")
        st["char_index"] = entry.get("char_index")
        if entry.get("correct"):
            st["correct"] += 1
            st["streak"] = st.get("streak", 0) + 1
            st["last_correct_ts"] = now
        else:
            st["fails"] += 1
            st["streak"] = 0
            if entry.get("feedback"):
                st["fixes"] = (st.get("fixes", []) + [entry["feedback"]])[-3:]
        _save(mem)
        with _journal_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps({**entry, "user": user, "ts": now}, ensure_ascii=False) + "\n")
        return dict(st)


def char_stats(lang: str, char: str, user: str = DEFAULT_USER) -> dict:
    with _lock:
        return dict(_load().get(user, {}).get(lang, {}).get(char, {}))


def lang_stats(lang: str, user: str = DEFAULT_USER) -> dict:
    with _lock:
        return dict(_load().get(user, {}).get(lang, {}))


def weakness(st: dict, now: float | None = None) -> float:
    """Higher = needs review more. Fail rate, plus a bump for recent misses, minus a streak bonus."""
    if not st or not st.get("attempts"):
        return 0.0
    now = now or time.time()
    fail_rate = st.get("fails", 0) / st["attempts"]
    recent_miss = 1.0 if st.get("streak", 0) == 0 and st.get("fails") else 0.0
    age_h = (now - st.get("last_ts", now)) / 3600
    return round(fail_rate + 0.5 * recent_miss + min(age_h / 24, 1) * 0.2 - 0.1 * min(st.get("streak", 0), 3), 3)


def _mastered(st: dict) -> bool:
    return bool(st) and st.get("correct", 0) > 0 and st.get("streak", 0) > 0


def choose_next(lang: str, item_id: str, char_index: int, action: str, user: str = DEFAULT_USER) -> dict:
    """Pick the concrete next step for action in {"retry", "advance", "review"}.
    Returns {lang, item_id, char_index, char, action, reason}."""
    lesson = content.load().get(lang)
    if not lesson or not lesson["items"]:
        return {"lang": lang, "item_id": item_id, "char_index": char_index, "char": None,
                "action": "stay", "reason": "no content for this language"}
    items = lesson["items"]
    by_id = {it["id"]: it for it in items}
    stats = lang_stats(lang, user)
    cur = by_id.get(item_id)

    def step(it, ci, act, why):
        return {"lang": lang, "item_id": it["id"], "char_index": ci, "char": it["chars"][ci] if it["chars"] else None,
                "action": act, "reason": why}

    if action == "retry" and cur:
        return step(cur, char_index, "retry", "same character again, the fix is fresh")

    if action == "review":
        weak = sorted(((weakness(st), c) for c, st in stats.items() if weakness(st) > 0.3), reverse=True)
        for w, c in weak:
            for it in items:
                if c in it["chars"] and not (it["id"] == item_id and it["chars"].index(c) == char_index):
                    return step(it, it["chars"].index(c), "review", f"{c} was missed before (weakness {w})")
        action = "advance"  # nothing weak to review

    if cur and char_index + 1 < len(cur["chars"]):
        return step(cur, char_index + 1, "advance", f"next character in {cur.get('meaning') or cur['id']}")

    # Item finished: first unseen item in content order, else the least-mastered other item.
    def mastery(it):
        return sum(_mastered(stats.get(c, {})) for c in it["chars"]) / max(1, len(it["chars"]))

    others = [it for it in items if it["id"] != item_id and it["chars"]]
    unseen = [it for it in others if not any(stats.get(c) for c in it["chars"])]
    if unseen:
        nxt = unseen[0]
        return step(nxt, 0, "advance", f"new item: {nxt.get('meaning') or nxt['id']}")
    if others:
        nxt = min(others, key=mastery)
        return step(nxt, 0, "advance", f"least practiced item: {nxt.get('meaning') or nxt['id']} "
                                       f"({int(mastery(nxt) * 100)}% mastered)")
    return step(cur or items[0], 0, "advance", "start over")


def journal(lang: str | None = None, user: str = DEFAULT_USER, limit: int = 200) -> list[dict]:
    out: list[dict] = []
    try:
        with _journal_path().open(encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("user", DEFAULT_USER) == user and (not lang or e.get("lang") == lang):
                    out.append(e)
    except FileNotFoundError:
        pass
    return out[-limit:][::-1]  # newest first


def daily5(user: str = DEFAULT_USER, n: int = 5) -> list[dict]:
    """Daily 5: the weakest characters across languages, then learned-but-stale ones,
    then unseen ones in content order, so the list is never empty."""
    now = time.time()
    mem = _load().get(user, {})
    langs = content.load()
    picks: list[tuple[float, dict]] = []
    seen_chars = set()
    for lang, lesson in langs.items():
        stats = mem.get(lang, {})
        for it in lesson["items"]:
            for ci, c in enumerate(it["chars"]):
                if (lang, c) in seen_chars:
                    continue
                seen_chars.add((lang, c))
                st = stats.get(c)
                if not st:
                    continue
                w = weakness(st, now)
                reason = (f"missed {st['fails']} of {st['attempts']} tries" if st.get("fails")
                          else "learned, keep it fresh")
                picks.append((w, {"lang": lang, "item_id": it["id"], "char_index": ci, "char": c,
                                  "meaning": it.get("meaning"), "romanization": it.get("romanization"),
                                  "reason": reason, "weakness": w, "stats": st}))
    picks.sort(key=lambda p: -p[0])
    out = [p[1] for p in picks[:n]]
    if len(out) < n:  # fill with unseen characters, one per language round-robin
        rank = {k: i for i, k in enumerate(config.LANG_ORDER)}
        queues = []
        for lang in sorted(langs, key=lambda l: rank.get(l, 99)):
            q = [(lang, it, ci, c) for it in langs[lang]["items"] for ci, c in enumerate(it["chars"])
                 if c not in mem.get(lang, {})]
            queues.append(q)
        while len(out) < n and any(queues):
            for q in queues:
                if q and len(out) < n:
                    lang, it, ci, c = q.pop(0)
                    if any(o["lang"] == lang and o["char"] == c for o in out):
                        continue
                    out.append({"lang": lang, "item_id": it["id"], "char_index": ci, "char": c,
                                "meaning": it.get("meaning"), "romanization": it.get("romanization"),
                                "reason": "new today", "weakness": 0.0, "stats": None})
    return out


def progress(lang: str | None, item_id: str | None, char_index: int, user: str = DEFAULT_USER) -> dict:
    out: dict[str, Any] = {"lang": lang}
    lesson = content.load().get(lang) if lang else None
    if not lesson:
        return out
    stats = lang_stats(lang, user)
    all_chars = {c for it in lesson["items"] for c in it["chars"]}
    learned = {c for c in all_chars if stats.get(c, {}).get("correct")}
    ids = [it["id"] for it in lesson["items"]]
    item = next((it for it in lesson["items"] if it["id"] == item_id), None)
    items_done = sum(1 for it in lesson["items"] if it["chars"] and all(stats.get(c, {}).get("correct") for c in it["chars"]))
    out.update({
        "item_id": item_id,
        "item_index": ids.index(item_id) if item_id in ids else None,
        "items_total": len(ids),
        "items_done": items_done,
        "char_index": char_index,
        "chars_total": len(item["chars"]) if item else 0,
        "learned": len(learned),
        "learnable": len(all_chars),
        "attempts": sum(st.get("attempts", 0) for st in stats.values()),
    })
    return out


def reset(user: str = DEFAULT_USER) -> None:
    with _lock:
        mem = _load()
        mem.pop(user, None)
        _save(mem)
        if _journal_path().exists():
            keep = [l for l in _journal_path().read_text(encoding="utf-8").splitlines()
                    if l.strip() and json.loads(l).get("user", DEFAULT_USER) != user]
            _journal_path().write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
