"""Writes content/names/{devanagari,arabic,cyrillic,hebrew,greek}.json: approximate English-sound -> script maps for
"write your name", and checks that every example rebuilds exactly from its sound keys.
   python3 content/tools/make_names.py

File shape:
  {script, lang, rtl, note, how_to_use, sounds: {key: glyph}, examples: [{name, sounds:[keys], written, note}]}
A UI can show the example list, or let someone tap sound keys in order and concatenate the glyphs.
These are rough, fun approximations (like name tags at a festival), not official transliterations.
"""
import json
from pathlib import Path

C = Path(__file__).resolve().parent.parent
OUT = C / "names"; OUT.mkdir(exist_ok=True)


# ---------------------------------------------------------------- devanagari
CONS = {"k": "क", "kh": "ख", "g": "ग", "gh": "घ", "ch": "च", "j": "ज", "t": "ट", "th": "थ", "d": "ड", "n": "न",
        "p": "प", "f": "फ़", "b": "ब", "bh": "भ", "m": "म", "y": "य", "r": "र", "l": "ल", "v": "व", "w": "व",
        "sh": "श", "s": "स", "h": "ह", "z": "ज़"}
SIGN = {"a": "", "aa": "ा", "i": "ि", "ee": "ी", "u": "ु", "oo": "ू", "e": "े", "ai": "ै", "o": "ो", "au": "ौ", "aw": "ॉ"}
INDEP = {"A": "अ", "AA": "आ", "I": "इ", "EE": "ई", "U": "उ", "OO": "ऊ", "E": "ए", "AI": "ऐ", "O": "ओ", "AU": "औ", "AW": "ऑ"}
D = dict(INDEP)
for c, g in CONS.items():
    D[c] = g                                # consonant with built-in 'a' (silent at the end of a word)
    D[c + "+"] = g + "्"                    # half form: joins the next consonant
    for v, s in SIGN.items():
        if v != "a":
            D[c + v] = g + s
D["M"] = "ं"  # nasal dot

devanagari = dict(
    script="Devanagari", lang="hindi", rtl=False,
    note="Hindi spells English names by sound. Capital keys (E, I, AA…) are vowel letters at the start of a syllable; "
         "lowercase keys are a consonant plus a vowel sign (maa = मा). 'n+' is a half letter that joins the next one. "
         "English 't' and 'd' usually use ट and ड.",
    how_to_use="Split the name into syllables, then look each one up and join them.",
    sounds=D,
    examples=[
        dict(name="Maria", sounds=["maa", "ri", "yaa"], written="मारिया"),
        dict(name="Emma", sounds=["E", "maa"], written="एमा"),
        dict(name="John", sounds=["jaw", "n"], written="जॉन", note="ॉ is the English 'aw/o' sound"),
        dict(name="Lisa", sounds=["li", "saa"], written="लिसा"),
        dict(name="Sam", sounds=["sai", "m"], written="सैम"),
        dict(name="David", sounds=["de", "vi", "d"], written="डेविड"),
        dict(name="Mike", sounds=["maa", "I", "k"], written="माइक"),
        dict(name="Anna", sounds=["A", "n+", "naa"], written="अन्ना"),
        dict(name="Ben", sounds=["be", "n"], written="बेन"),
        dict(name="Sarah", sounds=["saa", "raa"], written="सारा"),
    ])

# ---------------------------------------------------------------- arabic
A = {"aa": "ا", "Aa": "آ", "A": "أ", "E": "إ", "b": "ب", "p": "ب", "t": "ت", "th": "ث", "j": "ج", "g": "ج", "h": "ه",
     "kh": "خ", "d": "د", "r": "ر", "z": "ز", "s": "س", "sh": "ش", "f": "ف", "v": "ف", "q": "ق", "k": "ك", "c": "ك",
     "l": "ل", "m": "م", "n": "ن", "w": "و", "oo": "و", "o": "و", "y": "ي", "ee": "ي", "i": "ي", "ah": "ة"}
arabic = dict(
    script="Arabic", lang="arabic", rtl=True,
    note="Write right to left; letters join automatically when typed. Short vowels are usually left out, long ones use "
         "ا (aa), و (oo/o) and ي (ee/i). Arabic has no p, v or g, so they become ب, ف and ج. 'ah' at the end of a "
         "name is ة.",
    how_to_use="Write the consonants and long vowels in order, right to left.",
    sounds=A,
    examples=[
        dict(name="Maria", sounds=["m", "aa", "r", "ee", "aa"], written="ماريا"),
        dict(name="John", sounds=["j", "oo", "n"], written="جون"),
        dict(name="David", sounds=["d", "ee", "f", "ee", "d"], written="ديفيد"),
        dict(name="Sarah", sounds=["s", "aa", "r", "ah"], written="سارة"),
        dict(name="Adam", sounds=["Aa", "d", "m"], written="آدم"),
        dict(name="Lina", sounds=["l", "ee", "n", "aa"], written="لينا"),
        dict(name="Sam", sounds=["s", "aa", "m"], written="سام"),
        dict(name="Mike", sounds=["m", "aa", "y", "k"], written="مايك"),
        dict(name="Emma", sounds=["E", "ee", "m", "aa"], written="إيما"),
        dict(name="Anna", sounds=["Aa", "n", "aa"], written="آنا"),
    ])

# ---------------------------------------------------------------- cyrillic
R = {"a": "а", "b": "б", "v": "в", "w": "у", "g": "г", "d": "д", "e": "е", "eh": "э", "yo": "ё", "zh": "ж", "z": "з",
     "i": "и", "ee": "и", "y": "й", "k": "к", "c": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р",
     "s": "с", "t": "т", "u": "у", "oo": "у", "f": "ф", "h": "х", "kh": "х", "ts": "ц", "ch": "ч", "sh": "ш",
     "j": "дж", "yu": "ю", "ya": "я", "x": "кс", "th": "т"}
cyrillic = dict(
    script="Cyrillic", lang="russian", rtl=False,
    note="Russian spells names by sound, one letter per sound. English 'j' is дж, 'h' is х, the short 'e' in Sam or "
         "Ben is э at the start or after hard sounds, and 'th' usually becomes т. Capitalize the first letter.",
    how_to_use="Look up each sound in order, then capitalize the first letter.",
    sounds=R,
    examples=[
        dict(name="Maria", sounds=["m", "a", "r", "i", "ya"], written="Мария"),
        dict(name="John", sounds=["j", "o", "n"], written="Джон"),
        dict(name="David", sounds=["d", "eh", "v", "i", "d"], written="Дэвид"),
        dict(name="Sarah", sounds=["s", "a", "r", "a"], written="Сара"),
        dict(name="Mike", sounds=["m", "a", "y", "k"], written="Майк"),
        dict(name="Emma", sounds=["eh", "m", "m", "a"], written="Эмма"),
        dict(name="Anna", sounds=["a", "n", "n", "a"], written="Анна"),
        dict(name="Sam", sounds=["s", "eh", "m"], written="Сэм"),
        dict(name="Ben", sounds=["b", "e", "n"], written="Бен"),
        dict(name="Lisa", sounds=["l", "i", "z", "a"], written="Лиза"),
    ])


# ---------------------------------------------------------------- hebrew
H = {"A": "א", "b": "ב", "v": "ב", "g": "ג", "j": "ג'", "d": "ד", "h": "ה", "ah": "ה", "w": "ו", "o": "ו", "u": "ו",
     "z": "ז", "ch": "ח", "t": "ט", "y": "י", "i": "י", "ai": "יי", "k": "ק", "c": "ק", "l": "ל", "m": "מ", "n": "נ",
     "s": "ס", "f": "פ", "p": "פ", "ts": "צ", "r": "ר", "sh": "ש", "a": "א",
     "m$": "ם", "n$": "ן", "k$": "ך", "f$": "ף", "ts$": "ץ"}
hebrew = dict(
    script="Hebrew", lang="hebrew", rtl=True,
    note="Write right to left. Most short vowels are left out; י (i/ee/y), ו (o/u) and a final ה (ah) show some. "
         "Five letters have a special final form at the end of a word (keys ending in $: ם ן ך ף ץ). "
         "English 'j' is ג' (with an apostrophe).",
    how_to_use="Write the consonants and the vowels you hear clearly, right to left; use the $ form for the last letter.",
    sounds=H,
    examples=[
        dict(name="Maria", sounds=["m", "r", "i", "ah"], written="מריה"),
        dict(name="John", sounds=["j", "o", "n$"], written="ג'ון"),
        dict(name="Mike", sounds=["m", "ai", "k"], written="מייק"),
        dict(name="Emma", sounds=["A", "m", "ah"], written="אמה"),
        dict(name="Anna", sounds=["A", "n", "ah"], written="אנה"),
        dict(name="Sam", sounds=["s", "a", "m$"], written="סאם"),
        dict(name="Ben", sounds=["b", "n$"], written="בן"),
        dict(name="Lisa", sounds=["l", "i", "s", "ah"], written="ליסה"),
        dict(name="Lina", sounds=["l", "i", "n", "ah"], written="לינה"),
        dict(name="Adam", sounds=["A", "d", "m$"], written="אדם"),
    ])

# ---------------------------------------------------------------- greek
GK = {"a": "α", "á": "ά", "e": "ε", "é": "έ", "i": "ι", "í": "ί", "o": "ο", "ó": "ό", "u": "ου", "oo": "ου",
      "b": "μπ", "d": "ντ", "g": "γκ", "j": "τζ", "ch": "τσ", "sh": "σ", "z": "ζ", "th": "θ", "f": "φ", "k": "κ",
      "c": "κ", "l": "λ", "m": "μ", "n": "ν", "p": "π", "r": "ρ", "s": "σ", "s$": "ς", "t": "τ", "v": "β",
      "x": "ξ", "ks": "ξ", "ps": "ψ", "h": "χ", "y": "γι"}
greek = dict(
    script="Greek", lang="greek", rtl=False,
    note="Greek spells names by sound. Greek has no single b, d or g letter for those sounds, so they're written "
         "μπ, ντ, γκ; 'j' is τζ. Put the accent (á é í ó) on the stressed vowel, use ς for an 's' at the very end, "
         "and capitalize the first letter.",
    how_to_use="Look up each sound in order, accent the stressed vowel, then capitalize the first letter.",
    sounds=GK,
    examples=[
        dict(name="Maria", sounds=["m", "a", "r", "í", "a"], written="Μαρία"),
        dict(name="John", sounds=["j", "o", "n"], written="Τζον"),
        dict(name="David", sounds=["d", "é", "i", "v", "i", "d"], written="Ντέιβιντ"),
        dict(name="Sarah", sounds=["s", "á", "r", "a"], written="Σάρα"),
        dict(name="Mike", sounds=["m", "á", "i", "k"], written="Μάικ"),
        dict(name="Emma", sounds=["é", "m", "m", "a"], written="Έμμα"),
        dict(name="Anna", sounds=["á", "n", "n", "a"], written="Άννα"),
        dict(name="Sam", sounds=["s", "a", "m"], written="Σαμ"),
        dict(name="Ben", sounds=["b", "e", "n"], written="Μπεν"),
        dict(name="Lisa", sounds=["l", "í", "z", "a"], written="Λίζα"),
    ])


def build(d, cap=False):
    for ex in d["examples"]:
        got = "".join(d["sounds"][k] for k in ex["sounds"])
        if cap:
            got = got[:1].upper() + got[1:]
        assert got == ex["written"], (d["script"], ex["name"], got, ex["written"])


for f in OUT.glob("*.json"):
    f.unlink()  # rebuild from scratch (drops cut scripts such as katakana)
for fname, d, cap in (("devanagari", devanagari, False), ("arabic", arabic, False), ("cyrillic", cyrillic, True),
                      ("hebrew", hebrew, False), ("greek", greek, True)):
    build(d, cap)
    (OUT / f"{fname}.json").write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"names/{fname}.json: {len(d['sounds'])} sounds, {len(d['examples'])} examples OK")
