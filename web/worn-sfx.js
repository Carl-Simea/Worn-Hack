/* Reaction sounds from content/sfx (agent C), picked by content/reactions.json (owner: agent B).
   WornSfx.play("ding")                 play one sound
   WornSfx.forResult(result) -> {sound, line, kind}   pick + play the sound for a /grade result
   Browsers only allow audio after a tap; on /glasses pass ?sound=1. */
(function () {
  "use strict";
  var api = "", rx = null, cache = {}, lastLine = {}, streak = 0;
  var NAMES = ["boing", "buzzer", "cheer", "ding", "drumroll", "kiss", "slide", "sparkle", "tada"];

  function init(base) {
    api = base || "";
    fetch(api + "/static/content/reactions.json").then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { rx = j; }).catch(function () {});
  }
  function allowed() {
    var ua = navigator.userActivation;
    return window.__wornSound === true || !!window.WornNative || !!(ua && ua.hasBeenActive);
  }
  function play(name, vol) {
    if (!name || NAMES.indexOf(name) < 0 || !allowed()) return;
    try {
      var a = cache[name];
      if (!a) { a = cache[name] = new Audio(api + "/static/content/sfx/" + name + ".wav"); a.preload = "auto"; }
      a.volume = vol === undefined ? 0.8 : vol;
      a.currentTime = 0;
      var p = a.play(); if (p && p.catch) p.catch(function () {});
    } catch (e) {}
  }
  function pick(list, key) {
    if (!list || !list.length) return "";
    var i = Math.floor(Math.random() * list.length);
    if (list.length > 1 && list[i] === lastLine[key]) i = (i + 1) % list.length;
    lastLine[key] = list[i];
    return list[i];
  }
  function kindOf(r) {
    if (r.correct) return "correct";
    return (r.score || 0) >= 50 ? "close" : "wrong";
  }
  function forResult(r, opts) {
    opts = opts || {};
    var kind = kindOf(r);
    streak = r.correct ? streak + 1 : 0;
    var group = rx && rx[kind];
    var sound = group ? (Math.random() < 0.35 && group.alt_sounds ? group.alt_sounds[Math.floor(Math.random() * group.alt_sounds.length)] : group.sound)
                      : ({ correct: "ding", close: "boing", wrong: "buzzer" })[kind];
    var line = r.reaction || pick(group && group.lines, kind);
    if (r.correct && (streak === 3 || streak === 5 || streak === 10) && rx && rx.streak) {
      sound = rx.streak.sound || "drumroll";
      var sl = pick(rx.streak.lines, "streak");
      if (sl) line = sl.replace("{n}", streak);
    }
    if (!opts.silent) {
      play(sound);
      if (r.correct) setTimeout(function () { play("sparkle", 0.45); }, 260);
    }
    return { sound: sound, line: line, kind: kind, streak: streak };
  }

  window.WornSfx = { init: init, play: play, forResult: forResult };
})();
