/* Scribi's deterministic commands (agent D). These ALWAYS win over the AI: if a phrase matches here, the glasses
 * do exactly this and say a 2–4 word confirmation. Only unmatched speech goes to the backend's AI.
 * Tested by glasses-android/tests/commands.test.js (node). Works in the glasses' Chrome 74 (no ?. / ??). */
(function (root) {
  "use strict";
  var LANGS = {
    mandarin: ["mandarin", "chinese", "china", "putonghua", "mandarine"],
    hindi: ["hindi", "hindu", "indie", "devanagari", "hindy"],
    arabic: ["arabic", "arabian", "arab", "arabics"],
    russian: ["russian", "russia", "rushin", "rushing", "cyrillic"],
    hebrew: ["hebrew", "hebrews", "ivrit", "hebru"],
    greek: ["greek", "greece", "grease", "greeks", "greet"]
  };
  var NAME = { mandarin: "Mandarin", hindi: "Hindi", arabic: "Arabic", russian: "Russian", hebrew: "Hebrew", greek: "Greek" };

  // filler stripped from the start (and "please" from the end): "um hey Scribi can you please take me home"
  var FILLER = /^(?:(?:um+|uh+|er+|so|ok(?:ay)?|hey|hi|yo|well|now|right|alright|and|oh|scribi|scribby|scribe|scribbie|scruby|please|can you|could you|would you|will you|can we|let's|lets|i want to|i wanna|i'd like to|i would like to|i want|go ahead and|just)\s+)+/;

  function norm(t) {
    t = String(t || "").toLowerCase().replace(/[’']/g, "'").replace(/[^\w\s']/g, " ").replace(/\s+/g, " ").trim();
    for (var i = 0; i < 3; i++) t = t.replace(FILLER, "");
    return t.replace(/\s+please$/, "").trim();
  }

  function lev(a, b) {
    if (a === b) return 0;
    var m = a.length, n = b.length, d = [], i, j;
    for (i = 0; i <= m; i++) d[i] = [i];
    for (j = 1; j <= n; j++) d[0][j] = j;
    for (i = 1; i <= m; i++) for (j = 1; j <= n; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[m][n];
  }

  function findLang(t) {
    var words = t.split(" ");
    for (var l in LANGS) {
      for (var k = 0; k < LANGS[l].length; k++) if ((" " + t + " ").indexOf(" " + LANGS[l][k] + " ") >= 0) return l;
    }
    // near-miss single words ("mandrin", "hebru"): edit distance ≤ 2 on words of 5+ letters
    for (var w = 0; w < words.length; w++) {
      if (words[w].length < 5) continue;
      for (var l2 in LANGS) if (lev(words[w], l2) <= 2) return l2;
    }
    return null;
  }

  // exact phrase lists (after norm); fuzzy: whole phrase within edit distance 2 (short commands only)
  var EXACT = [
    ["home", ["home", "go home", "take me home", "take me back home", "back home", "main menu", "menu", "start over", "home screen", "go to home", "go to the main menu"]],
    ["back", ["back", "go back", "undo", "back up", "previous screen", "go back one"]],
    ["exit", ["exit", "close", "close the app", "stop", "bye", "goodbye", "good bye", "bye scribi", "go to sleep", "stop listening", "that's all", "i'm finished for today"]],
    ["next", ["next", "next one", "next stroke", "continue", "keep going", "go on", "ready", "move on", "go", "okay next"]],
    ["previous", ["previous", "previous stroke", "last one", "go back a stroke"]],
    ["repeat", ["repeat", "say it again", "say that again", "again please", "what did you say", "pardon", "one more time"]],
    ["show_again", ["show me again", "show again", "watch again", "replay", "show me", "show me how"]],
    ["slower", ["slower", "slow down", "too fast", "more slowly"]],
    ["faster", ["faster", "speed up", "quicker"]],
    ["check", ["check", "check it", "check this", "check my writing", "grade", "grade it", "how did i do", "done", "i'm done", "finished", "i'm finished", "all done", "look at it", "look at this"]],
    ["skip", ["skip", "skip it", "skip this", "skip this one", "next word", "pass"]],
    ["meaning", ["what does this mean", "what does it mean", "what does that mean", "meaning", "what is this", "what's this", "translate"]],
    ["help", ["help", "what can i say", "commands", "how does this work", "how to use", "how do i use this"]],
    ["start", ["start", "begin", "let's go", "open it", "that one", "this one", "yes", "practice it", "let me write it", "start writing"]],
    ["name", ["write my name", "how do i write my name", "my name", "spell my name", "name"]],
    ["compose", ["write this word", "help me write", "write a word", "write something"]],
    ["daily5", ["daily five", "daily 5", "daily", "review", "my daily five"]],
    ["journal", ["journal", "open journal", "my journal", "my pages", "history"]],
    ["learn", ["learn", "lessons", "languages", "open learn", "learn something"]]
  ];

  function say(intent, args) {
    switch (intent) {
      case "home": return "Going home!";
      case "back": return "Going back.";
      case "exit": return "Bye for now!";
      case "learn": return args.lang ? "Opening " + NAME[args.lang] + "!" : "Pick a language!";
      case "compose": return args.text ? "Let's write " + args.text + "!" : "What word?";
      case "write_name": return args.name ? "Spelling " + args.name + "!" : "What's your name?";
      case "next": return "Next!";
      case "previous": return "Going back.";
      case "repeat": return "Once more.";
      case "show_again": return "Watch again!";
      case "slower": return "Slower now.";
      case "faster": return "Faster now.";
      case "check": return "Checking!";
      case "skip": return "Skipping!";
      case "meaning": return "";
      case "help": return "Here's what to say.";
      case "start": return "Let's go!";
      case "open": return { daily5: "Daily five!", journal: "Your journal!", learn: "Pick a language!", name: "What's your name?", compose: "What word?" }[args.screen] || "Opening!";
      default: return "";
    }
  }

  /** text → {intent, args, say} or null (= not a command; let the AI handle it).
   *  ctx.screen / ctx.phase / ctx.lang give context ("I'm done" = check in a lesson, exit elsewhere). */
  function command(text, ctx) {
    ctx = ctx || {};
    var t = norm(text), m, r = null;
    if (!t) return null;
    // ---- commands with slots
    if ((m = t.match(/^(?:my name is|my name's|i'm called|call me|write my name|spell my name|how do i write my name|how do you write my name)\s*(?:is\s+)?([a-z][a-z' -]{0,30})$/))) {
      var nm = m[1].trim().replace(/\b\w/g, function (c) { return c.toUpperCase(); });
      if (!/^(In|On|The|A)$/.test(nm)) r = { intent: "write_name", args: { name: nm } };
    }
    if (!r && (m = t.match(/^(?:how (?:do|would|can|should) (?:i|you|we) (?:write|say|spell)|help me write|write|teach me to write|show me how to write|how is) (.+?)(?: (?:in|into) ([a-z]+))?(?: written)?$/))) {
      var word = m[1].replace(/^(?:the word|a word|the)\s+/, "").trim(), wl = m[2] ? findLang(m[2]) : null;
      if (/^my name$/.test(word)) r = { intent: "open", args: { screen: "name" } };
      else if (word && !/^(this word|a word|something|it|this|that)$/.test(word) && word.split(" ").length <= 6)
        r = { intent: "compose", args: { text: word, lang: wl || (m[2] ? null : ctx.lang) || null } };
    }
    if (!r && (m = t.match(/^(?:learn|teach me|open|switch to|let's do|lets do|do|practice|study|go to|start|change to|try)\s+(?:some\s+)?([a-z]+)(?: please)?$/))) {
      var ll = findLang(m[1]);
      if (ll) r = { intent: "learn", args: { lang: ll } };
    }
    if (!r && t.split(" ").length <= 2) { var bl = findLang(t); if (bl) r = { intent: "learn", args: { lang: bl } }; }
    // ---- fixed phrases (exact, then fuzzy for short phrases)
    if (!r) {
      var best = null, bestD = 99;
      for (var i = 0; i < EXACT.length; i++) {
        for (var k = 0; k < EXACT[i][1].length; k++) {
          var p = EXACT[i][1][k];
          if (t === p) { best = EXACT[i][0]; bestD = 0; break; }
          if (t.length >= 4 && p.length >= 4) { var d = lev(t, p); var lim = p.length >= 9 ? 2 : 1; if (d <= lim && d < bestD) { best = EXACT[i][0]; bestD = d; } }
        }
        if (bestD === 0) break;
      }
      if (best) {
        if (best === "name") r = { intent: "open", args: { screen: "name" } };
        else if (best === "compose") r = { intent: "open", args: { screen: "compose" } };
        else if (best === "daily5" || best === "journal" || best === "learn") r = { intent: "open", args: { screen: best } };
        else r = { intent: best, args: {} };
      }
    }
    if (!r) return null;
    // ---- context: "I'm done" / "done" / "stop" mean check inside a lesson; "back"/"previous" step back a stroke there
    if (ctx.screen === "lesson" && r.intent === "exit" && /^(stop|i'm finished for today)$/.test(t) === false && /done|finish/.test(t)) r = { intent: "check", args: {} };
    if (ctx.screen !== "lesson" && r.intent === "check" && /^(i'm done|done|all done|i'm finished|finished)$/.test(t)) r = { intent: "exit", args: {} };
    if (ctx.screen === "idle" && r.intent !== "home") return null;   // idle: only "Hey Scribi" wakes (handled by the page)
    r.say = say(r.intent, r.args);
    r.norm = t;
    return r;
  }

  var api = { command: command, norm: norm, lev: lev, findLang: findLang };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WornCommands = api;
})(typeof window !== "undefined" ? window : this);
