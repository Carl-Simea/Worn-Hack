"""Hand-made stroke-order SVGs for Russian, Arabic and Hindi.
   python3 content/tools/make_strokes.py

Writes content/strokes/{lang}/{codepoint hex}.svg in the same format as the
KanjiVG files: 109x109 viewBox, one <path> per stroke, in writing order.
web/glasses.html animates these exactly like the Japanese ones.

Paths were traced over Noto Sans / Noto Naskh Arabic / Noto Sans Devanagari
at the same scale the glasses use, then ordered by standard handwriting rules:
  Russian: printed letters, top to bottom, left to right.
  Arabic:  isolated forms, main body right to left, dots and hamza last.
  Hindi:   letter body, then vertical stem(s), then the headline (shirorekha) last.
Hindi conjuncts and syllables with top marks are NOT here on purpose
(स्ते न्य हाँ हीं शौ है): they fall back to "trace the shape" until someone
who writes Hindi checks the order. Edit the table below, rerun."""
import json
from pathlib import Path

C = Path(__file__).resolve().parent.parent

STROKES = {
  "russian": {
    "П": ["M30,18 V92", "M30,18 H79 V92"],
    "р": ["M36,17 V92", "M36,26 C42,18 50,16 56,16 C68,16 76,26 76,43 C76,60 68,69 56,69 C48,69 41,65 36,59"],
    "и": ["M30,16 V92", "M30,92 L79,16", "M79,16 V92"],
    "в": ["M29,16 V92", "M29,16 H58 C72,16 78,22 78,32 C78,43 70,49 58,49 H29", "M29,49 H62 C76,49 84,57 84,70 C84,84 74,91 60,91 H29"],
    "е": ["M30,52 H85 C85,30 74,17 56,17 C38,17 25,32 25,54 C25,78 38,92 58,92 C68,92 76,89 81,86"],
    "т": ["M23,21 H85", "M54,21 V92"],
    "С": ["M82,22 C76,18 68,16 60,16 C40,16 27,31 27,54 C27,78 39,92 60,92 C69,92 76,90 80,88"],
    "п": ["M36,19 V92", "M36,19 H73 V92"],
    "а": ["M32,26 C40,20 48,18 56,18 C70,18 77,26 77,40 V91", "M77,51 C56,51 31,52 31,74 C31,86 40,92 50,92 C62,92 72,86 77,76"],
    "с": ["M80,22 C74,18 66,16 60,16 C40,16 27,31 27,54 C27,78 39,92 60,92 C69,92 76,90 80,88"],
    "б": ["M74,17 C60,18 48,20 42,26 C34,34 30,46 30,62 C30,82 38,92 54,92 C70,92 79,81 79,68 C79,55 71,45 57,45 C45,45 37,52 34,60"],
    "о": ["M54,17 C38,17 28,32 28,54 C28,77 38,92 54,92 C70,92 80,77 80,54 C80,32 70,17 54,17"],
    "Д": ["M40,17 C40,46 38,62 31,73", "M40,17 H76 V73", "M24,92 V73 H85 V92"],
    "Н": ["M27,16 V92", "M80,16 V92", "M27,52 H80"],
    "Г": ["M43,16 V92", "M43,17 H73"],
    "д": ["M42,16 C42,44 38,56 28,66", "M42,16 H71 V66", "M23,92 V67 H84 V92"],
    "у": ["M30,16 L55,72", "M85,16 L60,76 C56,86 50,91 40,91 C36,91 33,90 31,89"],
    "л": ["M40,17 C40,52 38,78 32,86 C29,90 25,90 20,89", "M40,17 H82 V90"],
  },
  "arabic": {
    "م": ["M34,50 H70 C76,42 66,28 58,20 C52,15 44,18 38,30 C34,38 32,46 33,56 C34,70 37,82 37,92"],
    "ر": ["M64,18 C70,30 78,44 78,56 C78,78 64,92 50,92 C42,92 36,89 30,85"],
    "ح": ["M24,27 C28,20 38,17 52,20 C62,22 72,25 83,25 C70,28 56,32 46,40 C34,50 27,60 27,72 C27,86 40,92 56,92 C66,92 76,89 85,84"],
    "ب": ["M90,20 C92,30 92,40 88,48 C76,56 56,58 42,58 C26,58 18,52 18,34", "M49,78 L55,84"],
    "ا": ["M57,18 C56,40 56,64 57,92"],
    "ش": ["M88,40 C90,50 88,60 84,62 C78,64 72,62 70,55 C70,62 66,64 60,62 C54,60 50,54 50,46 C52,58 50,70 42,78 C34,86 22,88 18,80 C14,72 16,64 18,58", "M76,31 L80,35", "M63,31 L67,35", "M70,22 L74,26"],
    "ك": ["M70,16 C72,40 74,62 77,80 C78,85 74,86 68,86 C54,87 40,87 27,86", "M58,48 C52,46 48,50 50,55 C46,58 46,63 56,62"],
    "ن": ["M78,36 C82,48 80,62 74,72 C66,82 56,91 46,91 C34,91 26,82 26,70 C26,64 27,60 29,54", "M48,22 L52,26"],
    "ع": ["M64,22 C56,16 44,18 42,28 C40,38 50,42 58,40 C62,39 66,37 66,35 C54,40 34,48 34,66 C34,84 50,92 66,92 C74,92 80,90 85,87"],
    "لا": ["M67,17 C67,36 66,52 63,62 C60,72 62,80 76,83 C66,87 52,88 41,88", "M33,35 C42,46 54,62 64,82"],
    "أ": ["M58,40 C57,58 57,76 57,93", "M56,18 C51,16 48,20 51,24 C47,26 48,29 55,28"],
    "ي": ["M79,22 C72,16 58,18 54,30 C50,40 60,46 70,50 C78,54 80,62 74,68 C64,76 46,76 36,72 C28,68 28,58 31,48", "M57,85 L61,89", "M41,86 L45,90"],
    "ل": ["M67,17 C68,40 70,60 69,72 C68,84 58,91 50,91 C40,91 36,84 36,74 C36,70 37,67 38,64"],
  },
  "hindi": {
    "न": ["M30,47 C24,50 24,62 32,66 C40,70 44,62 44,52 H70", "M71,21 V92", "M20,20 H88"],
    "म": ["M38,22 V50 C30,50 24,56 28,64 C32,72 42,70 42,62 C42,56 46,54 52,54 H74", "M74,21 V92", "M17,20 H92"],
    "ध": ["M44,42 C36,38 24,32 24,22 C24,14 38,12 42,20 C46,28 40,36 32,46 C24,56 24,72 38,76 C52,80 66,74 74,66", "M74,20 V92", "M60,19 H90"],
    "वा": ["M48,40 C34,36 20,44 20,56 C20,68 34,72 52,64", "M52,33 V82", "M76,33 V82", "M16,30 H92"],
    "द": ["M71,20 V34 H48 C34,36 28,48 30,58 C32,70 46,76 60,72", "M60,72 C64,64 72,60 74,66 C76,72 70,76 66,74 L72,90", "M25,18 H83"],
    "चा": ["M20,42 H48", "M30,44 C26,52 30,60 40,60 H56", "M56,30 V80", "M79,30 V80", "M16,30 H92"],
    "ल": ["M48,60 C50,50 50,40 40,38 C28,36 22,48 22,60 C22,74 34,82 46,86", "M73,20 V86", "M17,18 H92"],
    "य": ["M27,20 V44 C27,62 36,74 50,72 C58,70 64,64 68,58", "M68,18 V92", "M18,18 H90"],
    "क": ["M55,40 C40,38 22,44 22,56 C22,68 40,66 55,56", "M55,56 C66,44 86,44 88,58 C90,68 84,74 78,80", "M55,26 V82", "M16,24 H92"],
  },
}

HEADER = "<!-- Worn team, hand-made stroke order. Needs native-writer QA. -->"

def hexname(ch):
    return "-".join(f"{ord(c):x}" for c in ch)

def main():
    n = 0
    for lang, chars in STROKES.items():
        out = C / "strokes" / lang
        out.mkdir(parents=True, exist_ok=True)
        for ch, paths in chars.items():
            body = "".join(f'<path d="{p}"/>' for p in paths)
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 109 109">' + HEADER +
                   '<g fill="none" stroke="#000" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">' +
                   body + "</g></svg>")
            (out / f"{hexname(ch)}.svg").write_text(svg, encoding="utf-8")
            n += 1
    print(f"wrote {n} stroke files")

if __name__ == "__main__":
    main()
