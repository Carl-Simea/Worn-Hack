"""Lesson content, owned by agent C at content/{lang}.json.

Accepted schemas, so content can move to the new contract without breaking anyone:
  {lang, name, rtl, items:[{id, text, chars, romanization, meaning, audio}]}   (new)
  {lang, name, rtl, phrases:[...same...]}                                      (old)
Each lesson is returned with BOTH "items" and "phrases" (same list) and per-char info.
Files are re-read on every call so C's edits show up without a restart."""

from __future__ import annotations

import json
import logging

from . import config, strokes

log = logging.getLogger("worn.content")


def _normalize(data: dict) -> dict:
    lang = data["lang"]
    meta = config.LANGS.get(lang, {})
    items = data.get("items") or data.get("phrases") or []
    out_items = []
    for it in items:
        chars = list(it.get("chars") or [])
        out_items.append({
            **it,
            "chars": chars,
            "audio_url": static_url(it.get("audio")),
            "char_info": [{"char": c, "stroke_count": strokes.stroke_count(lang, c),
                           "stroke_url": strokes.stroke_url(lang, c)} for c in chars],
        })
    return {
        **data,
        "name": data.get("name") or meta.get("name", lang),
        "script": data.get("script") or meta.get("script"),
        "rtl": bool(data.get("rtl", meta.get("rtl", False))),
        "items": out_items,
        "phrases": out_items,
    }


def load() -> dict[str, dict]:
    langs: dict[str, dict] = {}
    for d in (config.SEED_DIR, config.CONTENT_DIR):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("lang") and data["lang"] not in config.CUT_LANGS:
                    langs[data["lang"]] = _normalize(data)
            except Exception as e:  # a teammate's bad file must not take the server down
                log.warning("skipping %s: %s", f, e)
    return langs


def ordered(langs: dict[str, dict] | None = None) -> list[dict]:
    langs = load() if langs is None else langs
    rank = {k: i for i, k in enumerate(config.LANG_ORDER)}
    return sorted(langs.values(), key=lambda l: rank.get(l["lang"], 99))


def find_item(lang: str, item_id: str) -> tuple[dict, dict] | None:
    lesson = load().get(lang)
    if not lesson:
        return None
    for it in lesson["items"]:
        if it["id"] == item_id:
            return lesson, it
    return None


def static_url(rel: str | None) -> str | None:
    if not rel:
        return None
    if rel.startswith(("http://", "https://", "/")):
        return rel
    return f"/static/content/{rel}" if (config.CONTENT_DIR / rel).exists() else None
