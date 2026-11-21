"""Writes content/{lang}.json for all 6 lessons. Edit the tables here, rerun.
   python3 content/tools/make_content.py"""
import json
from pathlib import Path

C = Path(__file__).resolve().parent.parent
IDS = ["hello", "thank_you", "yes", "no", "bathroom"]
MEANING = {"hello": "hello", "thank_you": "thank you", "yes": "yes", "no": "no",
           "bathroom": "where is the bathroom?"}

# id: (text, chars, romanization).  chars = what the learner writes, one per /grade.
LESSONS = {
  "mandarin": ("Mandarin Chinese", False, {
    "hello":     ("你好", ["你", "好"], "nǐ hǎo"),
    "thank_you": ("谢谢", ["谢", "谢"], "xièxie"),
    "yes":       ("是", ["是"], "shì"),
    "no":        ("不", ["不"], "bù"),
    "bathroom":  ("厕所在哪里？", ["厕", "所", "在", "哪", "里"], "cèsuǒ zài nǎlǐ?"),
  }),
  "hindi": ("Hindi", False, {  # chars are aksharas (syllable blocks), the unit you write
    "hello":     ("नमस्ते", ["न", "म", "स्ते"], "namaste"),
    "thank_you": ("धन्यवाद", ["ध", "न्य", "वा", "द"], "dhanyavād"),
    "yes":       ("हाँ", ["हाँ"], "hā̃"),
    "no":        ("नहीं", ["न", "हीं"], "nahī̃"),
    "bathroom":  ("शौचालय कहाँ है?", ["शौ", "चा", "ल", "य", "क", "हाँ", "है"], "śaucālay kahā̃ hai?"),
  }),
  "arabic": ("Arabic", True, {  # chars in reading order (right to left), isolated letters
    "hello":     ("مرحبا", ["م", "ر", "ح", "ب", "ا"], "marḥaban"),
    "thank_you": ("شكرا", ["ش", "ك", "ر", "ا"], "shukran"),
    "yes":       ("نعم", ["ن", "ع", "م"], "naʿam"),
    "no":        ("لا", ["لا"], "lā"),
    "bathroom":  ("أين الحمام؟", ["أ", "ي", "ن", "ا", "ل", "ح", "م", "ا", "م"], "ayna al-ḥammām?"),
  }),
  "russian": ("Russian", False, {
    "hello":     ("Привет", list("Привет"), "privet"),
    "thank_you": ("Спасибо", list("Спасибо"), "spasibo"),
    "yes":       ("Да", list("Да"), "da"),
    "no":        ("Нет", list("Нет"), "nyet"),
    "bathroom":  ("Где туалет?", list("Гдетуалет"), "gde tualet?"),
  }),
  "japanese": ("Japanese", False, {
    "hello":     ("こんにちは", list("こんにちは"), "konnichiwa"),
    "thank_you": ("ありがとう", list("ありがとう"), "arigatō"),
    "yes":       ("はい", list("はい"), "hai"),
    "no":        ("いいえ", list("いいえ"), "iie"),
    "bathroom":  ("トイレはどこですか？", list("トイレはどこですか"), "toire wa doko desu ka?"),
  }),
}
for lang, (name, rtl, rows) in LESSONS.items():
    phrases = []
    for pid in IDS:
        text, chars, rom = rows[pid]
        assert "".join(chars) == text.replace(" ", "").rstrip("?？؟") or lang == "arabic" and "".join(chars) == text.replace(" ", "").rstrip("؟"), (lang, pid)
        phrases.append({"id": pid, "text": text, "chars": chars, "romanization": rom,
                        "meaning": MEANING[pid], "audio": f"audio/{lang}/{pid}.m4a"})
    (C / f"{lang}.json").write_text(json.dumps({"lang": lang, "name": name, "rtl": rtl, "phrases": phrases},
                                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("wrote", sorted(p.name for p in C.glob("*.json")))
