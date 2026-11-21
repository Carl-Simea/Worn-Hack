/* Worn voice helpers for the web pages (owner: agent B).
 *
 * WornVoice.COMMANDS            what the wearer can say, grouped (the "What can I say" page and hints use it)
 * WornVoice.HINTS[screen]       the one-line "Say …" hint for a screen
 * WornVoice.recorder()          -> { start(): Promise, stop(): Promise<Blob wav>, cancel(), level }  16 kHz mono WAV, all local.
 *                               Stops by itself after ~1.1 s of quiet once speech was heard, or after 7 s.
 * WornVoice.send(api, {audio, text, screen}) -> Promise<{heard, intent, args, say, nav}>   POST /voice (multipart)
 * WornVoice.say(text)           speaks Scribi's line with the browser's own (on-device) voice
 */
(function () {
  "use strict";

  var COMMANDS = [
    { title: "Get around", items: [
      ["home", "Back to the start"], ["back", "One screen back"], ["open learn", "Pick a language"],
      ["open journal", "Your handwriting over time"], ["open daily five", "Five quick characters"], ["help", "What can I say?"] ] },
    { title: "Learn", items: [
      ["learn Mandarin", "Or Hindi, Arabic, Russian, Hebrew, Greek"], ["next", "Next stroke, or next word"], ["previous", "Go back one"],
      ["repeat", "Play it again"], ["slower", "Slow the animation down"], ["show me again", "Watch the whole character"],
      ["what does this mean", "Meaning and how it sounds"] ] },
    { title: "Check your writing", items: [
      ["check", "Or “I’m done”: the glasses read your paper"], ["skip", "Move on without checking"] ] },
    { title: "Make it yours", items: [
      ["how do I write thank you in Hebrew", "Any short phrase, any of the six scripts"],
      ["write my name, Anna", "Your name in five scripts"] ] }
  ];

  var HINTS = {
    home: "Hi, I’m Scribi. Say “learn Mandarin” or “help”",
    learn: "Say a language, like “learn Greek”",
    lang: "Say “next” to pick a word, or “back”",
    words: "Say “next” to pick a word, or “back”",
    practice: "Say “next” after each stroke, “check” when you’re done",
    lesson: "Say “next” after each stroke, “check” when you’re done",
    compose: "Say “how do I write good luck in Russian”",
    name: "Say “write my name, Anna”",
    daily: "Say “start”, then “next” as you go",
    journal: "Say “back” or “home”",
    help: "Say “home” when you’re ready",
    howto: "Say “home” when you’re ready"
  };

  function encodeWav(chunks, rate) {
    var n = 0, i, j;
    for (i = 0; i < chunks.length; i++) n += chunks[i].length;
    var buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf), o = 44;
    function str(off, s) { for (var k = 0; k < s.length; k++) v.setUint8(off + k, s.charCodeAt(k)); }
    str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE"); str(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
    v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, "data"); v.setUint32(40, n * 2, true);
    for (i = 0; i < chunks.length; i++) for (j = 0; j < chunks[i].length; j++, o += 2) {
      var x = Math.max(-1, Math.min(1, chunks[i][j]));
      v.setInt16(o, x < 0 ? x * 0x8000 : x * 0x7fff, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  // average-downsample Float32 to 16 kHz
  function down(input, from, to) {
    if (from === to) return new Float32Array(input);
    var ratio = from / to, len = Math.floor(input.length / ratio), out = new Float32Array(len);
    for (var i = 0; i < len; i++) {
      var a = Math.floor(i * ratio), b = Math.min(input.length, Math.floor((i + 1) * ratio)), s = 0;
      for (var k = a; k < b; k++) s += input[k];
      out[i] = s / Math.max(1, b - a);
    }
    return out;
  }

  function recorder(opts) {
    opts = opts || {};
    var RATE = 16000, ctx = null, stream = null, node = null, src = null, chunks = [], done = null, timer = null;
    var heard = false, quietMs = 0, startedAt = 0, r = { level: 0, onlevel: null, onauto: null };
    function cleanup() {
      clearTimeout(timer);
      try { node && node.disconnect(); src && src.disconnect(); } catch (e) {}
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      if (ctx && ctx.close) ctx.close().catch(function () {});
      ctx = stream = node = src = null;
    }
    r.start = function () {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return Promise.reject(new Error("This browser can’t use the microphone here (it needs https or localhost)."));
      chunks = []; heard = false; quietMs = 0; startedAt = Date.now();
      return navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }).then(function (s) {
        stream = s;
        var AC = window.AudioContext || window.webkitAudioContext;
        ctx = new AC();
        src = ctx.createMediaStreamSource(s);
        node = ctx.createScriptProcessor(4096, 1, 1);
        node.onaudioprocess = function (e) {
          var d = e.inputBuffer.getChannelData(0), sum = 0;
          for (var i = 0; i < d.length; i++) sum += d[i] * d[i];
          var rms = Math.sqrt(sum / d.length);
          r.level = Math.min(1, rms * 8);
          if (r.onlevel) r.onlevel(r.level);
          chunks.push(down(d, ctx.sampleRate, RATE));
          var ms = 1000 * d.length / ctx.sampleRate;
          if (rms > 0.02) { heard = true; quietMs = 0; } else if (heard) quietMs += ms;
          if ((heard && quietMs > (opts.silenceMs || 1100)) || Date.now() - startedAt > (opts.maxMs || 7000)) { if (r.onauto) r.onauto(); }
        };
        src.connect(node); node.connect(ctx.destination);
      });
    };
    r.stop = function () {
      var c = chunks;
      cleanup();
      return Promise.resolve(c.length ? encodeWav(c, RATE) : null);
    };
    r.cancel = function () { chunks = []; cleanup(); };
    r.heardSpeech = function () { return heard; };
    return r;
  }

  function send(api, o) {
    var fd = new FormData();
    if (o.audio) fd.append("audio", o.audio, "voice.wav");
    if (o.text) fd.append("text", o.text);
    fd.append("screen", o.screen || "home");
    return fetch((api || "") + "/voice", { method: "POST", body: fd, cache: "no-store" }).then(function (r) {
      return r.text().then(function (t) {
        var j = null; try { j = t ? JSON.parse(t) : null; } catch (e) {}
        if (!r.ok) { var err = new Error((j && (j.detail && (j.detail.message || j.detail) || j.message)) || "HTTP " + r.status); err.status = r.status; throw err; }
        return j || {};
      });
    });
  }

  function say(text) {
    try {
      if (!text || !window.speechSynthesis) return;
      speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(String(text).replace(/[“”]/g, ""));
      u.rate = 1.02; u.lang = "en-US";
      speechSynthesis.speak(u);
    } catch (e) {}
  }

  window.WornVoice = { COMMANDS: COMMANDS, HINTS: HINTS, recorder: recorder, send: send, say: say, encodeWav: encodeWav };
})();
