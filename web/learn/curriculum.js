/* Worn curriculum (owner: Favor). Builds a Duolingo-style path for each language from content/{lang}.json.
   Shape of every path:  1 character at a time  ->  2 at a time  ->  3 at a time  ->  short words  ->  full phrases  ->  review.
   Every writing step points at a char that already exists in a lesson file (phrase_id + char_index), so
   POST /session and the grader work unchanged and the glasses show the char inside its real phrase.
   Edit SOUNDS (what each char says) and MANDARIN_PATH (hand-built order) here. */
(function () {
  "use strict";

  var META = {
    mandarin: { short: "Mandarin", badge: "中", tts: "zh-CN", color: "#FF4B4B" },
    hindi:    { short: "Hindi",    badge: "अ", tts: "hi-IN", color: "#FF9600" },
    arabic:   { short: "Arabic",   badge: "ع", tts: "ar-SA", color: "#58CC02" },
    russian:  { short: "Russian",  badge: "Я", tts: "ru-RU", color: "#1CB0F6" },
    japanese: { short: "Japanese", badge: "あ", tts: "ja-JP", color: "#CE82FF" }
  };

  // What each char sounds like (and, for Mandarin, what it means on its own).
  var SOUNDS = {
    mandarin: {
      "不": ["bù", "no, not"], "是": ["shì", "yes, is"], "你": ["nǐ", "you"], "好": ["hǎo", "good"],
      "谢": ["xiè", "thank"], "厕": ["cè", "toilet"], "所": ["suǒ", "place"], "在": ["zài", "at, in"],
      "哪": ["nǎ", "which, where"], "里": ["lǐ", "inside"]
    },
    hindi: {
      "न": ["na"], "म": ["ma"], "स्ते": ["ste"], "ध": ["dha"], "न्य": ["nya"], "वा": ["vā"], "द": ["da"],
      "हाँ": ["hā̃"], "हीं": ["hī̃"], "शौ": ["śau"], "चा": ["cā"], "ल": ["la"], "य": ["ya"], "क": ["ka"], "है": ["hai"]
    },
    arabic: {
      "م": ["m (mīm)"], "ر": ["r (rā’)"], "ح": ["ḥ (ḥā’)"], "ب": ["b (bā’)"], "ا": ["ā (alif)"], "ش": ["sh (shīn)"],
      "ك": ["k (kāf)"], "ن": ["n (nūn)"], "ع": ["ʿ (ʿayn)"], "لا": ["lā (lām-alif)"], "أ": ["a (alif + hamza)"],
      "ي": ["y (yā’)"], "ل": ["l (lām)"]
    },
    russian: {
      "П": ["p"], "р": ["r"], "и": ["i (ee)"], "в": ["v"], "е": ["ye"], "т": ["t"], "С": ["s"], "п": ["p"],
      "а": ["a"], "с": ["s"], "б": ["b"], "о": ["o"], "Д": ["d"], "Н": ["n"], "Г": ["g"], "д": ["d"],
      "у": ["u (oo)"], "л": ["l"]
    },
    japanese: {
      "こ": ["ko"], "ん": ["n"], "に": ["ni"], "ち": ["chi"], "は": ["ha (wa)"], "あ": ["a"], "り": ["ri"],
      "が": ["ga"], "と": ["to"], "う": ["u"], "い": ["i"], "え": ["e"], "ト": ["to (katakana)"],
      "イ": ["i (katakana)"], "レ": ["re (katakana)"], "ど": ["do"], "で": ["de"], "す": ["su"], "か": ["ka"]
    }
  };

  // Mandarin is hand-built so the words make sense: single characters first, then the words they form.
  var MANDARIN_PATH = [
    { title: "Your first characters", sub: "One character at a time", lessons: [
      { chars: ["不"], name: "No" }, { chars: ["是"], name: "Yes" },
      { chars: ["你"], name: "You" }, { chars: ["好"], name: "Good" } ] },
    { title: "Two characters", sub: "Put two together to make a word", lessons: [
      { chars: ["你", "好"], name: "Hello", word: "hello" },
      { chars: ["谢", "谢"], name: "Thank you", word: "thank_you" },
      { chars: ["厕", "所"], name: "Toilet" } ] },
    { title: "Three characters", sub: "Ask where something is", lessons: [
      { chars: ["在", "哪", "里"], name: "Where is it?" } ] },
    { title: "Full phrases", sub: "Write and say the whole thing", lessons: [
      { phrase: "bathroom", name: "Where is the bathroom?" },
      { review: true, name: "All five phrases" } ] }
  ];

  var ORDER = ["yes", "no", "hello", "thank_you", "bathroom"];  // short phrases first

  function locate(lesson, ch) {
    var ps = lesson.phrases;
    for (var k = 0; k < ORDER.length; k++) {
      for (var j = 0; j < ps.length; j++) {
        if (ps[j].id !== ORDER[k]) continue;
        var i = ps[j].chars.indexOf(ch);
        if (i >= 0) return { phrase: ps[j].id, idx: i };
      }
    }
    return null;
  }
  function phraseById(lesson, id) { return lesson.phrases.filter(function (p) { return p.id === id; })[0]; }

  // A lesson's writing steps: [{ch, phrase, idx}]
  function stepsForChars(lesson, chars, wordId) {
    var w = wordId && phraseById(lesson, wordId);
    return chars.map(function (c, n) {
      if (w && w.chars[n] === c) return { ch: c, phrase: w.id, idx: n };  // keep 谢谢 as idx 0 then 1
      var at = locate(lesson, c);
      return at ? { ch: c, phrase: at.phrase, idx: at.idx } : null;
    }).filter(Boolean);
  }
  function stepsForPhrase(lesson, id) {
    var p = phraseById(lesson, id);
    return p ? p.chars.map(function (c, i) { return { ch: c, phrase: id, idx: i }; }) : [];
  }

  function generic(lesson) {
    var seen = [];
    ORDER.forEach(function (id) {
      var p = phraseById(lesson, id);
      if (p) p.chars.forEach(function (c) { if (seen.indexOf(c) < 0) seen.push(c); });
    });
    var units = [], i = 0;
    function take(n) { var g = seen.slice(i, i + n); i += n; return g; }
    var u1 = { title: "Your first characters", sub: "One character at a time", lessons: [] };
    for (var a = 0; a < 3 && i < seen.length; a++) { var g1 = take(1); u1.lessons.push({ chars: g1 }); }
    units.push(u1);
    var u2 = { title: "Two at a time", sub: "Two new characters per lesson", lessons: [] };
    for (var b = 0; b < 3 && i < seen.length; b++) u2.lessons.push({ chars: take(2) });
    units.push(u2);
    var u3 = { title: "Three at a time", sub: "Three new characters per lesson", lessons: [] };
    while (i < seen.length) {
      var g3 = take(3), last = u3.lessons[u3.lessons.length - 1];
      if (g3.length === 1 && last) last.chars = last.chars.concat(g3); else u3.lessons.push({ chars: g3 });  // no lonely 1-char lesson at the end
    }
    if (u3.lessons.length) units.push(u3);
    var short = [], long = [];
    ORDER.forEach(function (id) { var p = phraseById(lesson, id); if (p) (p.chars.length <= 3 ? short : long).push(p); });
    units.push({ title: "Short words", sub: "Your first real words", lessons: short.map(function (p) { return { phrase: p.id }; }) });
    units.push({ title: "Full phrases", sub: "Write and say the whole thing", lessons:
      long.map(function (p) { return { phrase: p.id }; }).concat([{ review: true, name: "All five phrases" }]) });
    return units;
  }

  // Turn the unit outline into lessons with ids, titles and steps.
  function build(lang, lesson) {
    var outline = lang === "mandarin" ? MANDARIN_PATH : generic(lesson);
    var units = [], n = 0;
    outline.forEach(function (u, ui) {
      var unit = { n: ui + 1, title: u.title, sub: u.sub, lessons: [] };
      u.lessons.forEach(function (L) {
        var steps, name, kind, phrase = null;
        if (L.review) {
          kind = "review"; name = L.name;
          steps = ORDER.map(function (id) { var p = phraseById(lesson, id); return p ? { ch: p.chars[0], phrase: id, idx: 0 } : null; }).filter(Boolean);
        } else if (L.phrase) {
          kind = "phrase"; phrase = phraseById(lesson, L.phrase);
          steps = stepsForPhrase(lesson, L.phrase); name = L.name || cap(phrase.meaning);
        } else {
          kind = L.word ? "word" : "chars"; phrase = L.word ? phraseById(lesson, L.word) : null;
          steps = stepsForChars(lesson, L.chars, L.word);
          name = L.name || L.chars.map(function (c) { return (SOUNDS[lang][c] || [c])[0].split(" ")[0]; }).join(" · ");
        }
        unit.lessons.push({ id: lang + "-" + (++n), lang: lang, unit: ui + 1, kind: kind, name: name,
          label: L.review ? "★" : steps.map(function (s) { return s.ch; }).filter(uniq).slice(0, 3).join(""),
          phrase: phrase ? phrase.id : null, steps: steps });
      });
      units.push(unit);
    });
    return units;
  }
  function uniq(v, i, a) { return a.indexOf(v) === i; }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  function sound(lang, ch) { var s = SOUNDS[lang] && SOUNDS[lang][ch]; return s ? s[0] : ""; }
  function gloss(lang, ch) { var s = SOUNDS[lang] && SOUNDS[lang][ch]; return s && s[1] ? s[1] : ""; }

  window.WornCurriculum = { META: META, SOUNDS: SOUNDS, build: build, sound: sound, gloss: gloss };
})();
