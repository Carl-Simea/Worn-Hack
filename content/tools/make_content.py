"""Writes content/{lang}.json for the 6 writing lessons. Edit the tables here, then rerun:
   python3 content/tools/make_content.py

Schema (backend reads id/text/chars/romanization/meaning/audio; the rest is extra for the UIs):
  {lang, name, script, script_type, rtl, about, stroke_order, stroke_source,
   phrases:[{id, text, chars, romanization, meaning, audio, how, why, dictation, stroke_order}]}
Every item here is listed in content/REVIEW.md for native-speaker checks. If unsure, cut it.
"""
import json
from pathlib import Path

C = Path(__file__).resolve().parent.parent
IDS = ["hello", "thank_you", "water", "friend", "one"]
MEANING = {"hello": "hello", "thank_you": "thank you", "water": "water", "friend": "friend", "one": "one"}

# Per-language "why it's useful" lines (one per item).
WHY = {
    "hello": "Greet someone in their own script on a card or a note.",
    "thank_you": "Write a real thank-you card to a host or to family.",
    "water": "Spot it on a menu, a sign or a bottle label.",
    "friend": "Sign a note to a friend. Writing it by hand helps you remember it.",
    "one": "Read quantities and order one of something off a menu.",
}

LESSONS = {
    "mandarin": dict(
        name="Mandarin Chinese", script="Simplified Chinese characters", script_type="logographic", rtl=False,
        about="Each character is one syllable with its own meaning. Pinyin with tone marks shows the sound.",
        stroke_order="standard", stroke_source="hanzi-writer-data (Make Me a Hanzi)",
        items={
            "hello": ("你好", ["你", "好"], "nǐ hǎo",
                      "Characters carry meaning, not single sounds: 你 'you' + 好 'good'.",
                      "Two characters. 你 has the 'person' part 亻 on the left; 好 is 女 then 子."),
            "thank_you": ("谢谢", ["谢", "谢"], "xièxie",
                          "One character is one syllable; saying 谢 twice is the everyday 'thanks'.",
                          "The same character twice. 谢 starts with the 'speech' part 讠 on the left."),
            "water": ("水", ["水"], "shuǐ",
                      "水 began as a picture of flowing water; many water words contain a form of it (氵).",
                      "One character, four strokes: the hooked middle line comes first."),
            "friend": ("朋友", ["朋", "友"], "péngyou",
                       "Two characters, two syllables: 朋 and 友 both carry the idea of 'friend'.",
                       "朋 is two 月 side by side; 友 starts with a short horizontal line."),
            "one": ("一", ["一"], "yī",
                    "Numbers are characters too: 一 is one stroke, 二 is two, 三 is three.",
                    "One horizontal stroke, left to right."),
        }),
    "hindi": dict(
        name="Hindi", script="Devanagari", script_type="abugida", rtl=False,
        about="Each consonant carries a built-in 'a'; vowel signs attach to it. The top line is usually drawn last.",
        stroke_order="suggested", stroke_source="hand-authored for Worn (suggested stroke order)",
        items={
            "hello": ("नमस्ते", ["न", "म", "स्ते"], "namaste",
                      "स्ते joins a half स to त, plus the 'e' sign on top.",
                      "Three blocks: न, म, then स्ते."),
            "thank_you": ("धन्यवाद", ["ध", "न्य", "वा", "द"], "dhanyavād",
                          "Vowel signs attach to consonants: वा is व plus the 'ā' sign ा.",
                          "Four blocks: ध, न्य, वा, द."),
            "water": ("पानी", ["पा", "नी"], "pānī",
                      "पा is प + ा ('ā'); नी is न + ी ('ī'), drawn to the right.",
                      "Two blocks: पा then नी."),
            "friend": ("दोस्त", ["दो", "स्त"], "dost",
                       "The last consonant drops its built-in 'a' in speech: दोस्त is said 'dost'.",
                       "Two blocks: दो, then स्त (half स joined to त)."),
            "one": ("एक", ["ए", "क"], "ek",
                    "ए is a vowel letter used at the start of a word; inside words vowels become signs.",
                    "Two letters: ए then क."),
        }),
    "arabic": dict(
        name="Arabic", script="Arabic script", script_type="abjad", rtl=True,
        about="Written right to left. Letters join and change shape; short vowels are usually not written.",
        stroke_order="suggested", stroke_source="hand-authored for Worn (suggested stroke order)",
        items={
            "hello": ("مرحبا", ["م", "ر", "ح", "ب", "ا", "مرحبا"], "marḥaban",
                      "Right to left, and letters join: each has a separate, start, middle and end form.",
                      "Five letters, right to left: م ر ح ب ا. Then write them joined."),
            "thank_you": ("شكرا", ["ش", "ك", "ر", "ا", "شكرا"], "shukran",
                          "Dots tell letters apart: ش has three dots, added after the main stroke.",
                          "Four letters: ش ك ر ا. ش has three dots on top."),
            "water": ("ماء", ["م", "ا", "ء", "ماء"], "māʾ",
                      "ء (hamza) marks a short catch in the throat; the long 'ā' is written with ا.",
                      "Three letters: م ا ء. Hamza sits on the line, on its own."),
            "friend": ("صديق", ["ص", "د", "ي", "ق", "صديق"], "ṣadīq",
                       "Some letters (ا د ذ ر ز و) never join the next one, so words can have gaps: صد يق.",
                       "Four letters: ص د ي ق. There's a gap after د."),
            "one": ("واحد", ["و", "ا", "ح", "د", "واحد"], "wāḥid",
                    "و and ا don't connect forward, so واحد is written in pieces: و, ا, then حد.",
                    "Four letters: و ا ح د. Only ح and د join."),
        }),
    "russian": dict(
        name="Russian", script="Cyrillic (print)", script_type="alphabet", rtl=False,
        about="An alphabet like English, with some look-alike letters that sound different. Russian cursive looks quite different from print.",
        stroke_order="suggested", stroke_source="hand-authored for Worn (suggested stroke order)",
        items={
            "hello": ("привет", list("привет"), "privet",
                      "Look-alikes trick you: р is 'r', в is 'v', and е is 'ye'.",
                      "Six letters: п р и в е т. Informal hello."),
            "thank_you": ("спасибо", list("спасибо"), "spasibo",
                          "с is 's' and б is 'b'. We practise print; handwritten cursive looks different.",
                          "Seven letters: с п а с и б о."),
            "water": ("вода", list("вода"), "voda",
                      "Unstressed о often sounds like 'a': вода is said 'va-DA'.",
                      "Four letters: в о д а."),
            "friend": ("друг", list("друг"), "drug",
                       "д is 'd', у is 'oo' and г is 'g'. In cursive, д and г look very different.",
                       "Four letters: д р у г."),
            "one": ("один", list("один"), "odin",
                    "и is 'ee' and н is 'n', not 'h'. Stress the second syllable: a-DEEN.",
                    "Four letters: о д и н."),
        }),
    "hebrew": dict(
        name="Hebrew", script="Hebrew alphabet (block print)", script_type="abjad", rtl=True,
        about="Written right to left with 22 letters; everyday writing leaves out most vowels. We teach block print letters; everyday handwriting uses a different cursive style.",
        stroke_order="suggested", stroke_source="hand-authored for Worn (suggested stroke order)",
        items={
            "hello": ("שלום", list("שלום"), "shalom",
                      "Right to left. ם is the special form of מ used only at the end of a word.",
                      "Four letters, right to left: ש ל ו ם."),
            "thank_you": ("תודה", list("תודה"), "toda",
                          "Most vowels aren't written: ו stands for the 'o' and the final ה for the 'a'.",
                          "Four letters, right to left: ת ו ד ה."),
            "water": ("מים", list("מים"), "mayim",
                      "Same letter, two shapes: the word starts with מ and ends with final ם.",
                      "Three letters, right to left: מ י ם."),
            "friend": ("חבר", list("חבר"), "chaver",
                       "ח is a throaty 'ch', like in Bach. The vowels a and e aren't written.",
                       "Three letters, right to left: ח ב ר."),
            "one": ("אחד", list("אחד"), "echad",
                    "א often carries a vowel without a sound of its own; here it starts 'e-chad'.",
                    "Three letters, right to left: א ח ד."),
        }),
    "greek": dict(
        name="Greek", script="Greek alphabet", script_type="alphabet", rtl=False,
        about="An alphabet written left to right. Some letters look familiar but sound different, and an accent mark shows the stressed syllable.",
        stroke_order="suggested", stroke_source="hand-authored for Worn (suggested stroke order)",
        items={
            "hello": ("γεια σου", list("γειασου"), "yia sou",
                      "γ before ει sounds like 'y', so γεια is 'yia'. ου together sound like 'oo'.",
                      "Two words: γεια, then σου. Seven letters in all."),
            "thank_you": ("ευχαριστώ", list("ευχαριστώ"), "efcharistó",
                          "Look-alikes sound different: χ is a throaty 'ch' and ρ is 'r'.",
                          "Nine letters. The accent goes on the last one: ώ."),
            "water": ("νερό", list("νερό"), "neró",
                      "ν looks like a v but is 'n'. The accent shows the stress: ne-RÓ.",
                      "Four letters: ν ε ρ ό."),
            "friend": ("φίλος", list("φίλος"), "fílos",
                       "ς is how σ is written at the very end of a word.",
                       "Five letters: φ ί λ ο ς. It ends with ς."),
            "one": ("ένα", list("ένα"), "éna",
                    "Most Greek words carry a written accent on the stressed vowel: É-na.",
                    "Three letters: έ ν α."),
        }),
}


# Per-character sound, aligned with chars (the backend shows it as session.char_romanization).
CHAR_ROM = {
    "mandarin": {"hello": ["nǐ", "hǎo"], "thank_you": ["xiè", "xie"], "water": ["shuǐ"], "friend": ["péng", "you"],
                 "one": ["yī"]},
    "hindi": {"hello": ["na", "ma", "ste"], "thank_you": ["dha", "nya", "vā", "d"], "water": ["pā", "nī"],
              "friend": ["do", "st"], "one": ["e", "k"]},
}
AR_LETTER = {"م": "m · mīm", "ر": "r · rāʾ", "ح": "ḥ · ḥāʾ", "ب": "b · bāʾ", "ا": "ā · alif", "ش": "sh · shīn",
             "ك": "k · kāf", "ء": "ʾ · hamza", "ص": "ṣ · ṣād", "د": "d · dāl", "ي": "ī · yāʾ", "ق": "q · qāf",
             "و": "w · wāw"}
HE_LETTER = {"ש": "sh · shin", "ל": "l · lamed", "ו": "o / v · vav", "ם": "m · final mem", "ת": "t · tav",
             "ד": "d · dalet", "ה": "h / a · he", "מ": "m · mem", "י": "y / i · yod", "ח": "ch · chet",
             "ב": "v / b · bet", "ר": "r · resh", "א": "(silent) · alef"}
GR_LETTER = {"γ": "y / g · gamma", "ε": "e · epsilon", "ι": "i · iota", "α": "a · alpha", "σ": "s · sigma",
             "ο": "o · omicron", "υ": "u · upsilon", "χ": "ch · chi", "ρ": "r · rho", "τ": "t · tau",
             "ώ": "ó · omega + accent", "ν": "n · nu", "ό": "ó · omicron + accent", "φ": "f · phi",
             "ί": "í · iota + accent", "λ": "l · lambda", "ς": "s · final sigma", "έ": "é · epsilon + accent"}
RU_LETTER = {"п": "p", "р": "r", "и": "i (ee)", "в": "v", "е": "ye / e", "т": "t", "с": "s", "а": "a", "б": "b",
             "о": "o", "д": "d", "у": "u (oo)", "г": "g", "н": "n"}


GR_OVERRIDE = {  # letter pairs that change sound
    "hello": {0: "y · gamma (γει = 'y')", 1: "· epsilon (part of the 'y')", 2: "· iota (part of the 'y')",
              5: "o · omicron (ου = 'oo')", 6: "· upsilon (ου = 'oo')"},
    "thank_you": {0: "e · epsilon (ευ = 'ef')", 1: "f · upsilon (ευ = 'ef')"},
}


def char_rom(lang, pid, chars, rom):
    if lang == "greek":
        return [GR_OVERRIDE.get(pid, {}).get(i, GR_LETTER[c]) for i, c in enumerate(chars)]
    if lang in CHAR_ROM:
        out = CHAR_ROM[lang][pid]
    elif lang == "arabic":
        out = [AR_LETTER[c] if c in AR_LETTER else rom for c in chars]   # last entry = the joined word
    else:
        table = {"russian": RU_LETTER, "hebrew": HE_LETTER, "greek": GR_LETTER}[lang]
        out = [table[c] for c in chars]
    assert len(out) == len(chars), (lang, pid)
    return out


HERO = {"mandarin": "你好", "hindi": "नमस्ते", "arabic": "مرحبا", "russian": "Привет", "hebrew": "שלום",
        "greek": "Γεια σου"}


def check(lang, pid, text, chars):
    joined = "".join(chars)
    if lang == "arabic":  # isolated letters, then the whole connected word last
        assert chars[-1] == text and "".join(chars[:-1]) == text, (lang, pid)
    else:
        assert joined == text.replace(" ", ""), (lang, pid, joined, text)


for lang, L in LESSONS.items():
    phrases = []
    for pid in IDS:
        text, chars, rom, how, dictation = L["items"][pid]
        check(lang, pid, text, chars)
        phrases.append({
            "id": pid, "text": text, "chars": chars, "romanization": rom, "meaning": MEANING[pid],
            "char_romanization": char_rom(lang, pid, chars, rom),
            "audio": f"audio/{lang}/{pid}.m4a", "how": how, "why": WHY[pid], "dictation": dictation,
            "stroke_order": L["stroke_order"],
        })
    out = {k: L[k] for k in ("name", "script", "script_type", "rtl", "about", "stroke_order", "stroke_source")}
    out = {"lang": lang, **out, "hero": HERO[lang], "phrases": phrases}
    (C / f"{lang}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for f in C.glob("*.json"):  # drop lessons that were cut (e.g. japanese)
    d = json.loads(f.read_text(encoding="utf-8"))
    if "phrases" in d and d.get("lang") not in LESSONS:
        f.unlink(); print("removed", f.name)
print("wrote", sorted(p.name for p in C.glob("*.json") if p.stem in LESSONS))
