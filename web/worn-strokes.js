/* Shared stroke-order animation for glasses.html and mirror.html (owner: agent C).
   Android 9 WebView safe: no ?. / ??.
   Usage: var a = WornStrokes.create(boxEl, labelEl, apiBase, opts); a.animate(session); a.stop();
   opts.ramp = true: each loop plays at the next speed in RAMP (slow, faster, full), then starts slow again,
   and the label says which ("slow" / "faster" / "full speed"). Off by default.
   Three renderers, picked by what the backend found in content/strokes/:
     .json -> hanzi-writer data (Mandarin)        true stroke order
     .svg  -> KanjiVG-format centerlines (Japanese kana; team-made Russian, Arabic, Hindi) true stroke order, numbered
     none  -> trace the font glyph outline: shape only, not stroke order */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var RAMP = [0.45, 0.85, 1.6];                 // loop speeds when opts.ramp: slow -> faster -> full, repeat
  var RAMP_NAME = ["slow", "faster", "full speed"];
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function create(box, label, api, opts) {
    api = api || ""; opts = opts || {};
    var token = 0, writer = null;
    function speed(loop) { return opts.ramp ? RAMP[loop % RAMP.length] : 1; }
    function tag(loop) { return opts.ramp ? " · " + RAMP_NAME[loop % RAMP.length] : ""; }
    function url(p) { return /^https?:/.test(p) ? p : api + p; }
    function say(t) { if (label) label.textContent = t; }

    function stop() {
      token++;
      if (writer) { try { writer.pauseAnimation(); } catch (e) {} writer = null; }
      box.innerHTML = ""; say("");
    }

    function animate(s) {
      stop();
      var tok = token, su = (s && s.stroke_url) || "";
      if (!s || !s.char) return;
      if (/\.json$/.test(su) && window.HanziWriter) return hanzi(s, tok);
      if (/\.svg$/.test(su)) return kanjivg(s, tok);
      return glyph(s, tok);
    }

    function hanzi(s, tok) {
      var data = null, size = box.clientWidth || 316;
      var w = writer = HanziWriter.create(box, s.char, {
        width: size, height: size, padding: Math.round(size * 0.03), showOutline: true, showCharacter: false,
        strokeColor: "#ffffff", outlineColor: "#2f3540", radicalColor: null,
        strokeAnimationSpeed: 0.9, delayBetweenStrokes: 250,
        charDataLoader: function (ch, done, fail) {
          fetch(url(s.stroke_url)).then(function (r) { return r.json(); })
            .then(function (d) { data = d; done(d); }).catch(fail);
        },
        onLoadCharDataError: function () { if (tok === token) { box.innerHTML = ""; glyph(s, tok); } }
      });
      function strokeOnce(i) { return new Promise(function (res) { w.animateStroke(i, { onComplete: res }); }); }
      (async function loop() {
        while (!data) { await sleep(50); if (tok !== token) return; }
        var n = data.strokes.length, loop = 0;
        while (tok === token) {
          var k = speed(loop);
          try { w._options.strokeAnimationSpeed = 0.9 * k; w._options.delayBetweenStrokes = 250 / k; } catch (e) {}
          await w.hideCharacter();
          for (var i = 0; i < n && tok === token; i++) {
            say("stroke " + (i + 1) + " of " + n + tag(loop));
            await strokeOnce(i);
            if (opts.ramp) await sleep(250 / k);
          }
          if (tok !== token) return;
          say(n + " strokes");
          await sleep(opts.ramp ? 1100 : 1800);
          loop++;
        }
      })();
    }

    function kanjivg(s, tok) {
      fetch(url(s.stroke_url)).then(function (r) { return r.text(); }).then(function (txt) {
        if (tok !== token) return;
        var src = new DOMParser().parseFromString(txt, "image/svg+xml");
        var ds = Array.prototype.map.call(src.getElementsByTagName("path"), function (p) { return p.getAttribute("d"); });
        var svg = document.createElementNS(NS, "svg");
        svg.setAttribute("viewBox", "0 0 109 109"); svg.setAttribute("width", "100%"); svg.setAttribute("height", "100%");
        var ghost = document.createElementNS(NS, "g"), ink = document.createElementNS(NS, "g"), nums = document.createElementNS(NS, "g");
        [[ghost, "#2f3540"], [ink, "#ffffff"]].forEach(function (g) {
          g[0].setAttribute("fill", "none"); g[0].setAttribute("stroke", g[1]); g[0].setAttribute("stroke-width", "5");
          g[0].setAttribute("stroke-linecap", "round"); g[0].setAttribute("stroke-linejoin", "round");
        });
        svg.appendChild(ghost); svg.appendChild(ink); svg.appendChild(nums);
        box.appendChild(svg);
        var strokes = ds.map(function (d, i) {
          var g = document.createElementNS(NS, "path"); g.setAttribute("d", d); ghost.appendChild(g);
          var p = document.createElementNS(NS, "path"); p.setAttribute("d", d); ink.appendChild(p);
          var len = p.getTotalLength(); p.style.strokeDasharray = len; p.style.strokeDashoffset = len;
          var st = p.getPointAtLength(0), t = document.createElementNS(NS, "text");
          t.setAttribute("x", st.x - 6); t.setAttribute("y", st.y - 3); t.setAttribute("font-size", "9");
          t.setAttribute("fill", "#5cd6ff"); t.textContent = String(i + 1); t.style.opacity = 0; nums.appendChild(t);
          return { p: p, len: len, num: t };
        });
        function draw(st, ms) {
          return new Promise(function (res) {
            var t0 = null;
            st.num.style.opacity = 1;
            (function step(ts) {
              if (tok !== token) return res();
              if (t0 === null) t0 = ts;
              var k = Math.min(1, (ts - t0) / ms);
              st.p.style.strokeDashoffset = st.len * (1 - k);
              if (k < 1) requestAnimationFrame(step); else res();
            })(performance.now());
          });
        }
        (async function loop() {
          var n = 0;
          while (tok === token) {
            var k = speed(n);
            strokes.forEach(function (st) { st.p.style.strokeDashoffset = st.len; st.num.style.opacity = 0; });
            for (var i = 0; i < strokes.length && tok === token; i++) {
              say("stroke " + (i + 1) + " of " + strokes.length + tag(n));
              await draw(strokes[i], (350 + strokes[i].len * 9) / k);
              await sleep(200 / k);
            }
            if (tok !== token) return;
            say(strokes.length + (strokes.length === 1 ? " stroke" : " strokes"));
            await sleep(opts.ramp ? 1100 : 1800);
            n++;
          }
        })();
      }).catch(function () { if (tok === token) glyph(s, tok); });
    }

    function glyph(s, tok) {
      var svg = document.createElementNS(NS, "svg");
      svg.setAttribute("viewBox", "0 0 300 300"); svg.setAttribute("width", "100%"); svg.setAttribute("height", "100%");
      var t = document.createElementNS(NS, "text");
      t.setAttribute("x", "150"); t.setAttribute("y", "150");
      t.setAttribute("text-anchor", "middle"); t.setAttribute("dominant-baseline", "central");
      t.setAttribute("font-size", s.char.length > 2 ? "150" : "210");
      t.setAttribute("stroke", "#ffffff"); t.setAttribute("stroke-width", "2.5"); t.setAttribute("fill", "#ffffff");
      if (s.rtl) t.setAttribute("direction", "rtl");
      t.textContent = s.char;
      svg.appendChild(t); box.appendChild(svg);
      say("trace the shape");
      var L = 2400;
      t.style.strokeDasharray = L;
      (async function loop() {
        var n = 0;
        while (tok === token) {
          var t0 = performance.now(), dur = 2600 / speed(n++);
          while (tok === token) {
            var k = Math.min(1, (performance.now() - t0) / dur);
            t.style.strokeDashoffset = L * (1 - k);
            t.style.fillOpacity = Math.max(0, (k - 0.7) / 0.3);
            if (k >= 1) break;
            await new Promise(requestAnimationFrame);
          }
          await sleep(2000);
        }
      })();
    }

    return { animate: animate, stop: stop };
  }

  window.WornStrokes = { create: create };
})();
