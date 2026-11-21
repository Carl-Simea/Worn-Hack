"""Writes content/phrases/examples.json: a hand-checked phrasebook the backend answers "Help me write" from
before any model (matching ignores case and punctuation).
   python3 content/tools/make_phrases.py

Shape (agent A's contract): {"phrases": {"<english phrase>": {"<lang>": {"native", "romanization", "note"?}}}}
Every entry is listed in content/REVIEW.md for native-speaker checks. If unsure, cut it.
Rules: everyday, neutral register; gendered forms are noted; no religious, political or slang content.
"""
import json
from pathlib import Path

C = Path(__file__).resolve().parent.parent
LANGS = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]

P = {
    "good morning": {
        "mandarin": ("早上好", "zǎoshang hǎo"),
        "hindi": ("सुप्रभात", "suprabhāt", "formal; many people also just say नमस्ते"),
        "arabic": ("صباح الخير", "ṣabāḥ al-khayr"),
        "russian": ("Доброе утро", "dobroye utro"),
        "hebrew": ("בוקר טוב", "boker tov"),
        "greek": ("Καλημέρα", "kaliméra"),
    },
    "nice to meet you": {
        "mandarin": ("很高兴认识你", "hěn gāoxìng rènshi nǐ"),
        "hindi": ("आपसे मिलकर अच्छा लगा", "āpse milkar acchā lagā"),
        "arabic": ("تشرفنا", "tasharrafnā"),
        "russian": ("Приятно познакомиться", "priyatno poznakomit'sya"),
        "hebrew": ("נעים מאוד", "na'im me'od"),
        "greek": ("Χάρηκα πολύ", "chárika polý"),
    },
    "see you tomorrow": {
        "mandarin": ("明天见", "míngtiān jiàn"),
        "hindi": ("कल मिलते हैं", "kal milte haiṁ"),
        "arabic": ("أراك غدا", "arāka ghadan", "to a man; to a woman: أراكِ غدا (arāki ghadan)"),
        "russian": ("До завтра", "do zavtra"),
        "hebrew": ("נתראה מחר", "nitra'e machar"),
        "greek": ("Τα λέμε αύριο", "ta léme ávrio"),
    },
    "happy birthday": {
        "mandarin": ("生日快乐", "shēngrì kuàilè"),
        "hindi": ("जन्मदिन मुबारक", "janmadin mubārak"),
        "arabic": ("عيد ميلاد سعيد", "ʿīd mīlād saʿīd"),
        "russian": ("С днём рождения", "s dnyom rozhdeniya"),
        "hebrew": ("יום הולדת שמח", "yom huledet sameach"),
        "greek": ("Χρόνια πολλά", "chrónia pollá", "literally 'many years'; the usual birthday wish"),
    },
    "thank you very much": {
        "mandarin": ("非常感谢", "fēicháng gǎnxiè"),
        "hindi": ("बहुत धन्यवाद", "bahut dhanyavād"),
        "arabic": ("شكرا جزيلا", "shukran jazīlan"),
        "russian": ("Большое спасибо", "bol'shoye spasibo"),
        "hebrew": ("תודה רבה", "toda raba"),
        "greek": ("Ευχαριστώ πολύ", "efcharistó polý"),
    },
    "good night": {
        "mandarin": ("晚安", "wǎn'ān"),
        "hindi": ("शुभ रात्रि", "śubh rātri"),
        "arabic": ("تصبح على خير", "tuṣbiḥ ʿalā khayr", "to a man; to a woman: تصبحين على خير (tuṣbiḥīn ʿalā khayr)"),
        "russian": ("Спокойной ночи", "spokoynoy nochi"),
        "hebrew": ("לילה טוב", "layla tov"),
        "greek": ("Καληνύχτα", "kalinýchta"),
    },
    "how are you": {
        "mandarin": ("你好吗", "nǐ hǎo ma"),
        "hindi": ("आप कैसे हैं", "āp kaise haiṁ", "to a man; to a woman: आप कैसी हैं (āp kaisī haiṁ)"),
        "arabic": ("كيف حالك", "kayfa ḥāluk"),
        "russian": ("Как дела", "kak dela"),
        "hebrew": ("מה נשמע", "ma nishma", "casual and works for anyone"),
        "greek": ("Τι κάνεις", "ti káneis", "informal; to someone you'd address formally: Τι κάνετε (ti kánete)"),
    },
}

out = {}
for en, row in P.items():
    assert set(row) == set(LANGS), en
    out[en] = {}
    for lang in LANGS:
        native, rom, *note = row[lang]
        out[en][lang] = {"native": native, "romanization": rom, **({"note": note[0]} if note else {})}

d = C / "phrases"; d.mkdir(exist_ok=True)
(d / "examples.json").write_text(json.dumps({
    "_about": "Hand-checked phrasebook for 'Help me write' (agent C). Answered before any model. Questions are written "
              "without '?' (matching ignores punctuation). Native-speaker check: content/REVIEW.md.",
    "phrases": out}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"phrases/examples.json: {len(out)} phrases × {len(LANGS)} languages")
