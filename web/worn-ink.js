/* WornInk: stroke-order renderer for all five scripts (owner: agent B).
 *
 *   var ink = WornInk.create(el, { theme: "glasses" | "paper", numbers: true, label: el2 });
 *   ink.load(session).then(function (n) { ... })   // session = GET /session shape {lang, char, stroke_url}
 *   ink.loop()                                     // animate every stroke, pause, repeat (practice)
 *   ink.sync(stroke, phase)                        // follow the glasses: strokes before `stroke` done,
 *                                                  // `stroke` (1-based) drawing, rest ghosted
 *   ink.full()                                     // whole character, no animation
 *   ink.stop()
 *
 * Data sources, picked from the session's stroke_url (content/strokes/, see content/README.md):
 *   .json with "medians"  -> hanzi-writer-data (Mandarin): per-stroke outline revealed along its median
 *   .svg                  -> centerlines in a 109 box: C's hand-authored suggested order
 *                            (Hindi, Arabic, Russian, Hebrew, Greek), drawn as pen lines
 *   .json with "outline"  -> Worn stroke file (Hindi, Arabic, Russian): Noto glyph outline revealed
 *                            stroke by stroke along hand-authored centerlines (see web/strokes/README.md)
 *   nothing               -> the font glyph, traced (shape only; label says so)
 * No ?. or ?? so it also runs in older WebViews.
 */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var uid = 0;
  var cache = {};

  var THEMES = {
    glasses: { ghost: "#262a33", done: "#ffffff", cur: "#9fb0ff", dot: "#9fb0ff", num: "#9fb0ff" },
    paper: { ghost: "var(--ink-ghost, #e3dccd)", done: "var(--ink, #1b1a17)", cur: "var(--accent, #2b4bee)",
             dot: "var(--accent, #2b4bee)", num: "var(--accent, #2b4bee)" }
  };

  function el(name, attrs, parent) {
    var e = document.createElementNS(NS, name);
    for (var k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function hexOf(ch) {
    var out = [];
    for (var i = 0; i < ch.length; i++) {
      var cp = ch.codePointAt(i);
      if (cp > 0xffff) i++;
      out.push(cp.toString(16));
    }
    return out.join("-");
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
  function firstPoint(d) {
    var m = /[Mm]\s*(-?[\d.]+)[\s,]*(-?[\d.]+)/.exec(d || "");
    return m ? [parseFloat(m[1]), parseFloat(m[2])] : null;
  }

  function fetchText(u) {
    if (!cache[u]) {
      cache[u] = fetch(u).then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); });
      cache[u].catch(function () { delete cache[u]; });
    }
    return cache[u];
  }

  /* -> {viewBox, transform, kind, strokes:[{fill, center, width, start}], outline} */
  function parse(url, txt) {
    if (/\.svg(\?|$)/.test(url)) {
      var src = new DOMParser().parseFromString(txt, "image/svg+xml");
      var ps = src.getElementsByTagName("path"), strokes = [];
      for (var i = 0; i < ps.length; i++) {
        var d = ps[i].getAttribute("d");
        strokes.push({ center: d, width: 5.2, start: firstPoint(d) });
      }
      return { kind: "pen", viewBox: "0 0 109 109", transform: null, strokes: strokes };
    }
    var j = JSON.parse(txt);
    if (j.medians) {
      return {
        kind: "hanzi", viewBox: "0 0 1024 1024", transform: "translate(0 900) scale(1 -1)",
        strokes: j.strokes.map(function (d, i) {
          var m = j.medians[i];
          var c = "M" + m.map(function (p) { return p[0] + " " + p[1]; }).join(" L");
          return { fill: d, center: c, width: 170, start: m[0], flipY: true };
        })
      };
    }
    if (j.outline) {
      return {
        kind: "worn", viewBox: j.viewBox, transform: j.transform || null, outline: j.outline,
        strokes: j.strokes.map(function (s) {
          return { center: s.d, width: s.w || j.width || 60, start: firstPoint(s.d) };
        })
      };
    }
    throw new Error("unknown stroke data");
  }

  function create(host, opts) {
    opts = opts || {};
    var theme = THEMES[opts.theme || "paper"];
    var id = "wink" + (++uid);
    var token = 0, data = null, nodes = [], svg = null, ghostTxt = null, kind = null, session = null;
    var label = opts.label || null;

    function say(t) { if (label && label.textContent !== t) label.textContent = t; }

    function build(d) {
      host.innerHTML = "";
      svg = el("svg", { viewBox: d.viewBox, width: "100%", height: "100%", "aria-hidden": "true",
                        preserveAspectRatio: "xMidYMid meet", "class": "wink" }, host);
      svg.style.display = "block";
      svg.style.overflow = "visible";
      var defs = el("defs", {}, svg);
      var root = el("g", { transform: d.transform }, svg);
      nodes = [];
      if (d.kind === "pen") {
        var gg = el("g", { fill: "none", stroke: theme.ghost, "stroke-width": 5.2, "stroke-linecap": "round", "stroke-linejoin": "round" }, root);
        d.strokes.forEach(function (s, i) {
          el("path", { d: s.center }, gg);
          var p = el("path", { d: s.center, fill: "none", stroke: theme.done, "stroke-width": s.width,
                               "stroke-linecap": "round", "stroke-linejoin": "round" }, root);
          nodes.push({ draw: p, paint: p, i: i });
        });
      } else {
        // ghost of the whole character
        if (d.kind === "hanzi") d.strokes.forEach(function (s) { el("path", { d: s.fill, fill: theme.ghost }, root); });
        else el("path", { d: d.outline, fill: theme.ghost, "fill-rule": "nonzero" }, root);
        d.strokes.forEach(function (s, i) {
          var m = el("mask", { id: id + "m" + i, maskUnits: "userSpaceOnUse", x: -2000, y: -2000, width: 6000, height: 6000 }, defs);
          var mp = el("path", { d: s.center, fill: "none", stroke: "#fff", "stroke-width": s.width, "stroke-linecap": "round",
                                "stroke-linejoin": "round" }, m);
          // mask content is in the user space of the referencing path, which already includes its transform
          var paint = el("path", { d: d.kind === "hanzi" ? s.fill : d.outline, fill: theme.done, mask: "url(#" + id + "m" + i + ")" }, svg);
          if (d.transform) paint.setAttribute("transform", d.transform);
          mp.style.visibility = "hidden";
          nodes.push({ draw: mp, paint: paint, i: i });
        });
      }
      // Dash by each path's measured length (not pathLength="1": older WebViews such as the glasses' Chrome 74 can
      // ignore it and draw dotted lines instead of a growing stroke).
      nodes.forEach(function (n) {
        var len = 0;
        try { len = n.draw.getTotalLength(); } catch (e) { len = 0; }
        n.len = len > 0 ? len : 1000;
        n.draw.setAttribute("stroke-dasharray", n.len + " " + (n.len + 1));
        n.draw.setAttribute("stroke-dashoffset", n.len);
      });
      // start dot + number for the current stroke
      var hint = el("g", { "class": "wink-hint", opacity: 0 }, svg);
      var r = d.kind === "hanzi" ? 34 : d.kind === "pen" ? 3.2 : (d.strokes[0] ? d.strokes[0].width * 0.32 : 10);
      var dot = el("circle", { r: r, fill: theme.dot }, hint);
      var num = el("text", { "font-size": r * 2.3, fill: theme.num, "font-family": "Inter, system-ui, sans-serif",
                             "font-weight": 700, "text-anchor": "middle" }, hint);
      nodes.hint = { g: hint, dot: dot, num: num, r: r };
    }

    function setStroke(i, frac, color) {
      var n = nodes[i];
      if (!n) return;
      n.draw.setAttribute("stroke-dashoffset", String((n.len || 1) * (1 - frac)));
      if (n.draw !== n.paint) n.draw.style.visibility = frac <= 0 ? "hidden" : "visible";
      else n.draw.style.visibility = frac <= 0 ? "hidden" : "visible";
      var col = color || theme.done;
      if (n.paint.getAttribute(n.draw === n.paint ? "stroke" : "fill") !== col) n.paint.setAttribute(n.draw === n.paint ? "stroke" : "fill", col);
    }

    function hint(i) {
      var h = nodes.hint;
      if (!h) return;
      var s = data && data.strokes[i];
      if (!s || !s.start || opts.numbers === false) { h.g.setAttribute("opacity", 0); return; }
      var x = s.start[0], y = s.start[1];
      if (s.flipY) y = 900 - y;
      h.dot.setAttribute("cx", x); h.dot.setAttribute("cy", y);
      h.num.setAttribute("x", x + h.r * 2.1); h.num.setAttribute("y", y - h.r * 1.2);
      h.num.textContent = String(i + 1);
      h.g.setAttribute("opacity", 1);
    }

    function animateStroke(i, ms, tok, color) {
      return new Promise(function (res) {
        var t0 = null;
        (function step(ts) {
          if (tok !== token) return res(false);
          if (t0 === null) t0 = ts;
          var k = Math.min(1, (ts - t0) / ms);
          setStroke(i, ease(k), color);
          if (k < 1) requestAnimationFrame(step); else res(true);
        })(performance.now());
      });
    }

    function glyph(s) {
      host.innerHTML = "";
      svg = el("svg", { viewBox: "0 0 300 300", width: "100%", height: "100%" }, host);
      svg.style.display = "block";
      var t = el("text", { x: 150, y: 158, "text-anchor": "middle", "dominant-baseline": "central",
        "font-size": s.char.length > 2 ? 150 : 210, fill: theme.done, stroke: theme.done, "stroke-width": 2,
        direction: s.rtl ? "rtl" : null, "class": "wink-glyph" }, svg);
      t.textContent = s.char;
      ghostTxt = t;
      kind = "glyph";
      return 1;
    }

    function load(s) {
      stop();
      session = s;
      var tok = token;
      if (!s || !s.char) { host.innerHTML = ""; return Promise.resolve(0); }
      var urls = [];
      if (s.stroke_url) urls.push(s.stroke_url);
      var base = opts.api || "";
      function tryNext(k) {
        if (k >= urls.length) return Promise.reject(new Error("no stroke data"));
        var u = /^https?:/.test(urls[k]) ? urls[k] : base + urls[k];
        return fetchText(u).then(function (t) { return parse(u, t); }).catch(function () { return tryNext(k + 1); });
      }
      return tryNext(0).then(function (d) {
        if (tok !== token) return 0;
        data = d; kind = d.kind; build(d);
        return d.strokes.length;
      }, function () {
        if (tok !== token) return 0;
        data = null;
        return glyph(s);
      });
    }

    function count() { return data ? data.strokes.length : (kind === "glyph" ? 1 : 0); }

    function full() {
      token++;
      if (kind === "glyph") { say(""); return; }
      for (var i = 0; i < nodes.length; i++) setStroke(i, 1);
      if (nodes.hint) nodes.hint.g.setAttribute("opacity", 0);
      say(count() + (count() === 1 ? " stroke" : " strokes"));
    }

    function glyphTrace(tok) {
      var t = ghostTxt, L = 2400;
      t.style.strokeDasharray = L;
      say("trace the shape");
      (async function loop() {
        while (tok === token) {
          var t0 = performance.now();
          while (tok === token) {
            var k = Math.min(1, (performance.now() - t0) / 2600);
            t.style.strokeDashoffset = L * (1 - k);
            t.style.fillOpacity = Math.max(0, (k - 0.7) / 0.3);
            if (k >= 1) break;
            await new Promise(requestAnimationFrame);
          }
          await sleep(2000);
        }
      })();
    }

    function loop() {
      token++;
      var tok = token;
      if (kind === "glyph") return glyphTrace(tok);
      if (!data) return;
      var n = data.strokes.length;
      (async function run() {
        while (tok === token) {
          for (var i = 0; i < n; i++) setStroke(i, 0);
          for (i = 0; i < n && tok === token; i++) {
            say("stroke " + (i + 1) + " of " + n);
            hint(i);
            await animateStroke(i, 520 + 240 * Math.min(2, data.strokes.length > 8 ? 1 : 1.4), tok, theme.cur);
            if (tok !== token) return;
            setStroke(i, 1, theme.done);
            await sleep(170);
          }
          if (tok !== token) return;
          if (nodes.hint) nodes.hint.g.setAttribute("opacity", 0);
          say(n + (n === 1 ? " stroke" : " strokes"));
          await sleep(1700);
        }
      })();
    }

    /* Follow the glasses. stroke is 1-based; phase "checking"/"celebrate"/"retry"/"result" shows it whole. */
    var syncKey = "";
    function sync(stroke, phase) {
      if (kind === "glyph") { if (syncKey !== "g") { syncKey = "g"; loop(); } return; }
      if (!data) return;
      var n = data.strokes.length;
      var whole = /check|celebr|result|retry|done|grad/.test(phase || "");
      var k = whole ? n + 1 : Math.max(1, Math.min(n, stroke || 1));
      var key = k + "|" + (phase === "demo" ? "demo" : "w");
      if (key === syncKey) return;
      syncKey = key;
      token++;
      var tok = token;
      if (phase === "demo" && !whole) return loop();
      for (var i = 0; i < n; i++) setStroke(i, i < k - 1 ? 1 : 0, theme.done);
      if (k > n) { if (nodes.hint) nodes.hint.g.setAttribute("opacity", 0); say(n + (n === 1 ? " stroke" : " strokes")); return; }
      say("stroke " + k + " of " + n);
      hint(k - 1);
      (async function again() {
        while (tok === token) {
          await animateStroke(k - 1, 760, tok, theme.cur);
          if (tok !== token) return;
          await sleep(900);
          if (tok !== token) return;
          setStroke(k - 1, 0);
          await sleep(160);
        }
      })();
    }

    /* Static: the first k strokes drawn, the rest ghosted (print worksheets). */
    function upTo(k) {
      token++; syncKey = "";
      if (kind === "glyph") { say(""); return; }
      for (var i = 0; i < nodes.length; i++) setStroke(i, i < k ? 1 : 0, i === k - 1 ? theme.cur : theme.done);
      if (nodes.hint) nodes.hint.g.setAttribute("opacity", 0);
    }

    function stop() { token++; syncKey = ""; }

    return { load: load, loop: loop, sync: sync, full: full, upTo: upTo, stop: stop, count: count,
             kind: function () { return kind; } };
  }

  /* Line the learner's chars up with the item text so word gaps survive (γεια σου).
     -> [{c: "γ", i: 0}, ..., {gap: " "}, {c: "σ", i: 4}, ...]. Extra chars (a joined Arabic word) are appended. */
  function segments(text, chars) {
    var out = [], pos = 0;
    text = text || "";
    (chars || []).forEach(function (c, i) {
      var at = text.indexOf(c, pos);
      if (at >= 0 && /^[\s\u00a0.,!?;:¿¡،؟।'"\-]*$/.test(text.slice(pos, at))) {
        if (at > pos && /\s/.test(text.slice(pos, at))) out.push({ gap: " " });
        pos = at + c.length;
      } else if (out.length && c.length > 1) {
        out.push({ gap: " " }); // the joined word after its letters
      }
      out.push({ c: c, i: i });
    });
    return out;
  }

  window.WornInk = { create: create, hexOf: hexOf, segments: segments };
})();
