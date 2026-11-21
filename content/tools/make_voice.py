"""Writes content/voice/{commands,screens,tests}.json: what the wearer can say, and what each glasses screen tells
them to say next. Data only; the matcher is content/tools/voice_match.py (reference, ported to JS by D, used by A).
   python3 content/tools/make_voice.py        # writes the files, then runs every test case through voice_match

Screen ids (agreed with D): home, learn, words, lesson (phase watch|your_turn|check|result), name, compose, daily5,
journal, howto. Hints are short enough for the 640x480 glasses (<= 40 chars a line, checked below).
Placeholders in "say"/"hint": {language} {word} {text} {meaning} {romanization} {n} {m} {score} {fix} {name} {screen}
are filled by whoever speaks the line; the matcher fills the ones it knows.
"""
import json
import sys
import unicodedata
from pathlib import Path

C = Path(__file__).resolve().parent.parent
LANGS = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]


def fold(s):
    """ā → a, ó → o, drop apostrophes/ʿ: what a speech recognizer would type for a romanization."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch == " ")).lower().strip()


# Spoken names, plus what recognizers often type instead (tested by ear on Google/Apple dictation patterns).
LANGUAGE = {
    "mandarin": ["mandarin", "chinese", "mandarin chinese", "mandarine", "mandrin"],
    "hindi": ["hindi", "indy", "hindu", "hindy", "devanagari"],
    "arabic": ["arabic", "arabian", "arabick"],
    "russian": ["russian", "cyrillic", "russia"],
    "hebrew": ["hebrew", "he brew", "hebrews", "ivrit"],
    "greek": ["greek", "greece", "greek language"],
}

WORD_EN = {
    "hello": ["hello", "hi", "say hello", "greeting"],
    "thank_you": ["thank you", "thanks", "thankyou"],
    "water": ["water"],
    "friend": ["friend", "a friend", "my friend"],
    "one": ["one", "number one", "the number one", "won"],
}

SCREEN = {
    "home": ["home", "home screen", "main menu", "menu", "start"],
    "learn": ["learn", "lessons", "languages", "learn a language", "scripts", "learning"],
    "name": ["write my name", "my name", "name", "names", "write your name"],
    "compose": ["help me write", "help me right", "write a message", "a message", "phrasebook", "phrases"],
    "daily5": ["daily five", "daily", "daily review", "review", "five a day", "my daily five"],
    "journal": ["journal", "my journal", "history", "progress", "my writing"],
    "howto": ["how to use", "how to", "tutorial", "instructions", "guide", "help", "help screen", "how it works"],
}
SCREEN_TITLE = {"home": "Home", "learn": "Learn", "words": "Words", "lesson": "Lesson", "name": "Write my name",
                "compose": "Help me write", "daily5": "Daily 5", "journal": "Journal", "howto": "How to use"}

# Stripped from the start of what was heard before matching (longest first in the matcher).
FILLERS = ["hey worn", "ok worn", "okay worn", "hi worn", "worn", "please", "okay", "ok", "um", "uh", "so", "and",
           "can you", "could you", "can i", "i want to", "i wanna", "i'd like to", "id like to", "let's", "lets",
           "now", "go ahead and", "just"]

# Order matters: the matcher tries intents top to bottom, exact phrases before slot templates.
# "phrases": the whole utterance must be one of these (after fillers). "templates": {slot} patterns, whole utterance.
# "screens": only on these screens (omit = everywhere). "nav": the screen to go to ("<back>" = one level up).
INTENTS = [
    {"id": "help", "phrases": ["help", "what can i say", "what do i say", "commands", "options", "i'm stuck",
                               "im stuck", "what now", "what do i do", "what can you do", "help me", "say commands"],
     "say": "You can say: {suggestions}."},
    {"id": "home", "phrases": ["home", "go home", "main menu", "menu", "go to home", "take me home", "home screen",
                               "back to home", "back to start", "go to the start"], "nav": "home", "say": "Home."},
    {"id": "back", "phrases": ["back", "go back", "back up", "return", "exit", "close", "leave", "cancel",
                               "never mind", "nevermind"], "nav": "<back>"},
    {"id": "check", "phrases": ["check", "check it", "check this", "check my writing", "check my work", "czech",
                                "chuck", "i'm done", "im done", "done", "i am done", "finished", "i'm finished",
                                "im finished", "grade", "grade it", "grade me", "how did i do", "all done",
                                "that's it", "thats it", "look", "look at this", "is this right", "did i get it"],
     "screens": ["lesson", "name", "compose", "daily5"], "say": "Checking."},
    {"id": "next", "phrases": ["next", "next one", "next stroke", "go on", "continue", "keep going", "carry on",
                               "move on", "necks", "nxt", "forward", "next please", "ok next", "got it"],
     "say": ""},
    {"id": "skip", "phrases": ["skip", "skip it", "skip this", "skip this one", "skip word", "skip this word",
                               "next word", "pass", "another word", "different word", "something else"],
     "screens": ["lesson", "daily5", "words"], "say": "Skipping."},
    {"id": "previous", "phrases": ["previous", "previous one", "go back one", "last one", "back one",
                                   "previous word", "the one before", "before"], "say": ""},
    {"id": "show_again", "phrases": ["show me again", "show again", "show me", "show it again", "replay",
                                     "watch again", "play again", "show me how", "how do i write it",
                                     "how do i write this", "show me the strokes", "draw it again"],
     "screens": ["lesson", "name", "compose", "daily5"], "say": "Watch."},
    {"id": "repeat", "phrases": ["repeat", "repeat that", "again", "say it again", "say that again", "one more time",
                                 "what", "pardon", "sorry", "come again", "say it", "how do you say it",
                                 "how do i say it", "pronounce it"], "say": "{text}. {romanization}."},
    {"id": "slower", "phrases": ["slower", "slow down", "too fast", "more slowly", "slowly", "go slower",
                                 "slower please", "take it slow"], "say": "Slower."},
    {"id": "faster", "phrases": ["faster", "speed up", "too slow", "go faster", "quicker"], "say": "Faster."},
    {"id": "meaning", "phrases": ["what does this mean", "what does it mean", "what does that mean", "meaning",
                                  "what's this", "whats this", "what is this", "what is that", "translate",
                                  "translation", "what am i writing", "what word is this"],
     "say": "{text} means {meaning}."},
    {"id": "retry", "phrases": ["try again", "let me try again", "retry", "redo", "do it again", "once more",
                                "let me try"], "screens": ["lesson", "name", "compose", "daily5"],
     "say": "Okay, again."},
    # Free-text slots first, so "write my name" isn't swallowed by the screen alias.
    {"id": "write_name", "templates": ["write my name {name} in {language}", "write my name in {language} {name}",
                                       "my name is {name} in {language}", "spell my name {name} in {language}",
                                       "write my name {name}", "write my name is {name}", "my name is {name}",
                                       "my names {name}", "spell my name {name}", "spell {name}",
                                       "write the name {name}", "name {name}", "how do i write my name {name}",
                                       "how do i write {name} as a name"],
     "nav": "name", "say": "{name}. Pick a script, or say a language."},
    {"id": "how_write", "templates": ["how do i write {text} in {language}", "how do you write {text} in {language}",
                                      "how to write {text} in {language}", "help me write {text} in {language}",
                                      "help me right {text} in {language}", "write {text} in {language}",
                                      "how do i say {text} in {language}", "how do you say {text} in {language}",
                                      "what is {text} in {language}", "whats {text} in {language}",
                                      "how do i write {text}", "help me write {text}", "how do you write {text}"],
     "nav": "compose", "say": "Here's {text} in {language}."},
    {"id": "learn", "templates": ["learn {language}", "teach me {language}", "open {language}", "switch to {language}",
                                  "change to {language}", "go to {language}", "practice {language}",
                                  "study {language}", "start {language}", "i want {language}", "{language}",
                                  "{language} please", "let's do {language}", "do {language}"],
     "nav": "words", "say": "{language}. Pick a word."},
    {"id": "word", "templates": ["{word}", "learn {word}", "practice {word}", "open {word}", "write {word}",
                                 "do {word}", "the word {word}", "{word} please", "teach me {word}",
                                 "{word} in {language}", "learn {word} in {language}", "write {word} in {language}"],
     "screens": ["words", "lesson", "learn", "home"], "nav": "lesson", "say": "{word}."},
    {"id": "open", "templates": ["open {screen}", "go to {screen}", "show {screen}", "show me {screen}",
                                 "take me to {screen}", "open the {screen}", "go to the {screen}", "{screen}",
                                 "start {screen}", "do {screen}", "let's do {screen}"],
     "nav": "{screen}", "say": "{screen_title}."},
]

NOT_UNDERSTOOD = ["Sorry, I didn't catch that.", "I didn't get that."]
NOT_HERE = "You can't do that here."
UNKNOWN_LANGUAGE = {"starts": ["learn", "teach me", "switch to", "practice", "study"],
                    "say": "I can teach Mandarin, Hindi, Arabic, Russian, Hebrew and Greek."}

# What each screen shows (hint, <= 40 chars a line) and says on entry, and the 3-4 suggestions "help" reads out.
SCREENS = {
    "home": {"title": "Worn", "say": "Hi! Say learn, write my name, or help.",
             "hint": "Say “learn”, “daily five” or “help”",
             "suggestions": ["learn Mandarin", "write my name, Maria", "daily five", "how to use"],
             "menu": [{"label": "Learn", "say": "learn", "screen": "learn"},
                      {"label": "Write my name", "say": "write my name", "screen": "name"},
                      {"label": "Help me write", "say": "help me write", "screen": "compose"},
                      {"label": "Daily 5", "say": "daily five", "screen": "daily5"},
                      {"label": "Journal", "say": "journal", "screen": "journal"},
                      {"label": "How to use", "say": "how to use", "screen": "howto"}]},
    "learn": {"title": "Learn", "breadcrumb": ["Home", "Learn"], "say": "Which language? Say its name.",
              "hint": "Say a language, like “Greek”",
              "suggestions": ["Mandarin", "Hindi", "Arabic", "Russian", "Hebrew", "Greek"]},
    "words": {"title": "{language}", "breadcrumb": ["Home", "Learn", "{language}"],
              "say": "{language}. Say a word: hello, thank you, water, friend, or one.",
              "hint": "Say a word, like “hello”",
              "suggestions": ["hello", "thank you", "water", "friend", "one", "back"]},
    "lesson": {"title": "{word}", "breadcrumb": ["Learn", "{language}", "{word}"],
               "suggestions": ["check", "show me again", "slower", "skip", "what does this mean"],
               "phases": {
                   "watch": {"say": "{word}. {romanization}. Watch.", "hint": "Watch… say “show me again”",
                             "after": "Your turn. Say next when you're ready."},
                   "your_turn": {"say": "Stroke {n} of {m}.", "hint": "Write stroke {n} of {m}",
                                 "hint2": "Say “next” or “I'm done”",
                                 "last": "Last stroke! Say done when it's on paper."},
                   "check": {"say": "Let me look.", "hint": "Checking your writing…"},
                   "result": {"pass": {"say": "{reaction} Say next for the next word.",
                                       "hint": "Say “next” or “try again”"},
                              "retry": {"say": "{fix} Say try again, or skip.",
                                        "hint": "Say “try again” or “skip”"},
                              "word_done": {"say": "That's {word} in {language}! Say next.",
                                            "hint": "Say “next word” or “home”"},
                              "language_done": {"say": "You've done every {language} word! Say home, or a "
                                                       "new language.", "hint": "Say “home” or a language"}},
               }},
    "name": {"title": "Write my name", "breadcrumb": ["Home", "Write my name"],
             "say": "Say your name, like: my name is Maria.",
             "hint": "Say “my name is …”", "hint2": "Then a language, like “Greek”",
             "after_name": "{name}. Say a language: Hindi, Arabic, Russian, Hebrew, or Greek.",
             "shown": "That's {name} in {language}. Write it, then say done.",
             "suggestions": ["my name is Maria", "Greek", "check", "back"]},
    "compose": {"title": "Help me write", "breadcrumb": ["Home", "Help me write"],
                "say": "What do you want to write? Say: how do I write good morning in Greek.",
                "hint": "Say “how do I write … in …”", "hint2": "e.g. “good night in Hebrew”",
                "shown": "{text} in {language}. Write it, then say done.",
                "failed": "I couldn't write that one. Try a shorter phrase.",
                "suggestions": ["how do I write good morning in Greek", "happy birthday in Hindi",
                                "check", "back"]},
    "daily5": {"title": "Daily 5", "breadcrumb": ["Home", "Daily 5"],
               "say": "Five quick words from memory. Here's the first.",
               "hint": "Write it from memory", "hint2": "Say “I'm done” or “show me”",
               "item": "Word {n} of 5: {meaning}. Write it in {language}.",
               "done": "Daily five done! {score} of 5. Say home.",
               "empty": "Learn a few words first. Say learn.",
               "suggestions": ["I'm done", "show me again", "skip", "home"]},
    "journal": {"title": "Journal", "breadcrumb": ["Home", "Journal"],
                "say": "Your journal. Say next or previous to flip pages.",
                "hint": "Say “next”, “previous” or “home”",
                "empty": "Nothing here yet. Say learn to write your first word.",
                "suggestions": ["next", "previous", "home"]},
    "howto": {"title": "How to use", "breadcrumb": ["Home", "How to use"],
              "say": "Here's how Worn works. Say next for each tip.",
              "hint": "Say “next” or “home”",
              "pages": [
                  {"title": "Just talk", "lines": ["Say what you want.", "“Learn Greek”, “home”, “back”."],
                   "say": "Just talk. Say what you want, like learn Greek, home, or back."},
                  {"title": "Watch, then write", "lines": ["Watch each stroke.", "Write it on paper, big and dark."],
                   "say": "Watch each stroke, then write it on paper with a dark pen."},
                  {"title": "Say done", "lines": ["Look at your paper.", "Say “I'm done” to check it."],
                   "say": "Look at your paper and say I'm done. I'll check it."},
                  {"title": "Stuck?", "lines": ["“Show me again”, “slower”,", "“skip”, or “what can I say”."],
                   "say": "Stuck? Say show me again, slower, skip, or what can I say."},
                  {"title": "Button", "lines": ["Press: next, or open the item.", "Hold: check.  Double tap: back."],
                   "say": "The button is a backup. Press for next, hold to check, double tap to go back."},
                  {"title": "Your name", "lines": ["Say “my name is …”.", "Then a script."],
                   "say": "Say my name is, then your name, and I'll spell it in a new script."}],
              "suggestions": ["next", "previous", "home"]},
}

# heard (with screen) → expected intent and args. Run by voice_match.py --test (and below).
TESTS = [
    ("home", "home", "home", {}), ("lesson", "take me home", "home", {}), ("words", "go back", "back", {}),
    ("lesson", "Back.", "back", {}), ("home", "open learn", "open", {"screen": "learn"}),
    ("home", "open journal", "open", {"screen": "journal"}), ("home", "open daily five", "open", {"screen": "daily5"}),
    ("home", "open daily 5", "open", {"screen": "daily5"}), ("home", "open help", "open", {"screen": "howto"}),
    ("home", "How to use", "open", {"screen": "howto"}), ("home", "journal", "open", {"screen": "journal"}),
    ("home", "Help me write", "open", {"screen": "compose"}), ("home", "write my name", "open", {"screen": "name"}),
    ("home", "learn Mandarin", "learn", {"language": "mandarin"}), ("home", "Learn Hindi.", "learn", {"language": "hindi"}),
    ("learn", "arabic", "learn", {"language": "arabic"}), ("home", "teach me Russian", "learn", {"language": "russian"}),
    ("learn", "Hebrew please", "learn", {"language": "hebrew"}), ("lesson", "switch to Greek", "learn", {"language": "greek"}),
    ("learn", "Chinese", "learn", {"language": "mandarin"}), ("learn", "learn mandrin", "learn", {"language": "mandarin"}),
    ("learn", "Indy", "learn", {"language": "hindi"}), ("home", "hey worn, learn greek", "learn", {"language": "greek"}),
    ("words", "hello", "word", {"word": "hello"}), ("words", "Thank you!", "word", {"word": "thank_you"}),
    ("words", "water please", "word", {"word": "water"}), ("words", "friend", "word", {"word": "friend"}),
    ("words", "one", "word", {"word": "one"}), ("words", "number one", "word", {"word": "one"}),
    ("words", "shalom", "word", {"word": "hello"}), ("words", "namaste", "word", {"word": "hello"}),
    ("home", "hello in hebrew", "word", {"word": "hello", "language": "hebrew"}),
    ("lesson", "next", "next", {}), ("lesson", "Next one.", "next", {}), ("lesson", "okay next", "next", {}),
    ("lesson", "previous", "previous", {}), ("lesson", "repeat", "repeat", {}), ("lesson", "say it again", "repeat", {}),
    ("lesson", "slower", "slower", {}), ("lesson", "slow down please", "slower", {}),
    ("lesson", "show me again", "show_again", {}), ("lesson", "replay", "show_again", {}),
    ("lesson", "check", "check", {}), ("lesson", "I'm done", "check", {}), ("lesson", "I'm done.", "check", {}),
    ("lesson", "Czech", "check", {}), ("lesson", "how did I do?", "check", {}), ("lesson", "skip", "skip", {}),
    ("lesson", "skip this one", "skip", {}), ("lesson", "next word", "skip", {}), ("lesson", "try again", "retry", {}),
    ("lesson", "what does this mean?", "meaning", {}), ("lesson", "What's this", "meaning", {}),
    ("home", "help", "help", {}), ("lesson", "what can I say", "help", {}), ("lesson", "um, help", "help", {}),
    ("home", "how do I write good morning in Greek", "how_write", {"text": "good morning", "language": "greek"}),
    ("compose", "How do I write happy birthday in Hindi?", "how_write",
     {"text": "happy birthday", "language": "hindi"}),
    ("compose", "how do you say thank you very much in Russian", "how_write",
     {"text": "thank you very much", "language": "russian"}),
    ("compose", "help me write good night", "how_write", {"text": "good night"}),
    ("home", "write my name, Maria", "write_name", {"name": "Maria"}),
    ("home", "Write my name Sam", "write_name", {"name": "Sam"}),
    ("home", "my name is Anna", "write_name", {"name": "Anna"}),
    ("home", "my name is Lina in Arabic", "write_name", {"name": "Lina", "language": "arabic"}),
    ("name", "write my name John in Greek", "write_name", {"name": "John", "language": "greek"}),
    ("name", "greek", "learn", {"language": "greek"}),
    ("lesson", "nxt", "next", {}), ("lesson", "chek", "check", {}), ("lesson", "show me agin", "show_again", {}),
    ("lesson", "", None, {}), ("lesson", "the", None, {}), ("lesson", "banana pancakes", None, {}),
    ("home", "check", None, {}), ("home", "learn klingon", None, {}),
]

# ---------------------------------------------------------------------------------------------------------------

def word_aliases():
    out = {k: list(v) for k, v in WORD_EN.items()}
    for lang in LANGS:
        for p in json.loads((C / f"{lang}.json").read_text(encoding="utf-8"))["phrases"]:
            r = fold(p["romanization"])
            if r and r not in out[p["id"]] and r not in ("drug",):   # "drug" heard as English: skip
                out[p["id"]].append(r)
    out["hello"] += ["ni hao", "nee how", "yassou", "yasou", "geia sou", "marhaba", "privyet"]
    out["thank_you"] += ["xie xie", "shay shay", "shukran", "spaseebo", "efharisto", "toda raba"]
    out["friend"] += ["droog", "drook", "peng you", "haver", "sadik", "filos"]
    out["one"] += ["yi", "ek", "wahid", "odin", "echad", "ena", "ehad"]
    return {k: sorted(set(v), key=lambda s: (-len(s), s)) for k, v in out.items()}


def main():
    d = C / "voice"; d.mkdir(exist_ok=True)
    langs = {l: json.loads((C / f"{l}.json").read_text(encoding="utf-8")) for l in LANGS}
    commands = {
        "_about": "Voice commands for Worn (agent C). Generated by content/tools/make_voice.py; matcher: "
                  "content/tools/voice_match.py. Match the whole utterance after removing fillers: intents in order, "
                  "'phrases' before 'templates'; then a fuzzy pass. Respect 'screens'.",
        "version": 1,
        "screens": list(SCREEN_TITLE),
        "screen_titles": SCREEN_TITLE,
        "fillers": sorted(FILLERS, key=lambda s: (-len(s), s)),
        "numbers": {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five"},
        "aliases": {"language": LANGUAGE, "word": word_aliases(), "screen": SCREEN},
        "language_names": {l: langs[l]["name"].replace(" Chinese", "") for l in LANGS},
        "word_names": {"hello": "hello", "thank_you": "thank you", "water": "water", "friend": "friend", "one": "one"},
        "intents": INTENTS,
        "not_understood": NOT_UNDERSTOOD,
        "not_here": NOT_HERE,
        "unknown_language": UNKNOWN_LANGUAGE,
        "fuzzy": {"min_ratio": 0.8, "max_words": 4},
    }
    (d / "commands.json").write_text(json.dumps(commands, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (d / "screens.json").write_text(json.dumps({
        "_about": "What each glasses screen shows and says (agent C). Every screen tells the wearer what to say next. "
                  "'hint'/'hint2' are on-screen lines (<= 40 chars); 'say' is spoken on entry. {placeholders} are "
                  "filled at runtime.", "screens": SCREENS}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (d / "tests.json").write_text(json.dumps({
        "_about": "heard → expected intent (null = not understood). Run: python3 content/tools/voice_match.py --test",
        "cases": [{"screen": s, "heard": h, "intent": i, "args": a} for s, h, i, a in TESTS]},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    bad = []
    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("hint", "hint2", "lines") or path.endswith("lines"):
                    for line in ([v] if isinstance(v, str) else v):
                        if len(line) > 40:
                            bad.append(f"{path}.{k}: {len(line)} chars: {line}")
                else:
                    walk(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    walk(SCREENS, "screens")
    for b in bad:
        print("TOO LONG", b)
    sys.path.insert(0, str(Path(__file__).parent))
    import voice_match
    fails = voice_match.run_tests()
    print(f"voice/: {len(INTENTS)} intents, {len(SCREENS)} screens, {len(TESTS)} tests, {fails} failing, "
          f"{len(bad)} hints too long")
    return 1 if fails or bad else 0


if __name__ == "__main__":
    sys.exit(main())
