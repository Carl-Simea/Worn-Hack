#!/bin/zsh
# Regenerates content/audio/{lang}/{id}.m4a with macOS voices. Run from repo root.
cd "${0:A:h}/../.." || exit 1
python3 - <<'PY' | while IFS=$'\t' read -r lang id voice text; do
import json
V = {"mandarin": "Tingting", "hindi": "Lekha", "arabic": "Majed", "russian": "Milena", "hebrew": "Carmit", "greek": "Melina"}
for lang, voice in V.items():
    for p in json.load(open(f"content/{lang}.json", encoding="utf-8"))["phrases"]:
        print(lang, p["id"], voice, p["text"], sep="\t")
PY
  mkdir -p "content/audio/$lang" &&
  say -v "$voice" -r 140 -o "/tmp/worn_$$.aiff" -- "$text" &&
  afconvert -f m4af -d aac -b 64000 "/tmp/worn_$$.aiff" "content/audio/$lang/$id.m4a" &&
  echo "ok $lang/$id"
done
rm -f /tmp/worn_$$.aiff
