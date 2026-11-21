/* Rainbow confetti, the one loud moment (owner: agent B).
   WornConfetti.burst({ x: 0.5, y: 0.4, count: 160 })  x/y are fractions of the viewport. */
(function () {
  "use strict";
  var canvas = null, ctx = null, parts = [], running = false, dpr = 1;
  var HUES = [0, 28, 50, 130, 195, 230, 280, 320];

  function ensure() {
    if (canvas) return;
    canvas = document.createElement("canvas");
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText = "position:fixed;inset:0;width:100vw;height:100vh;pointer-events:none;z-index:9999";
    document.body.appendChild(canvas);
    ctx = canvas.getContext("2d");
    resize();
    window.addEventListener("resize", resize);
  }
  function resize() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(innerWidth * dpr);
    canvas.height = Math.round(innerHeight * dpr);
  }

  function burst(o) {
    o = o || {};
    ensure();
    var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    var n = Math.round((o.count || 160) * (reduced ? 0.25 : 1));
    var cx = (o.x === undefined ? 0.5 : o.x) * innerWidth, cy = (o.y === undefined ? 0.45 : o.y) * innerHeight;
    var spread = o.spread || 1;
    for (var i = 0; i < n; i++) {
      var a = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.3 * spread;
      var v = (7 + Math.random() * 11) * (o.power || 1);
      parts.push({
        x: cx + (Math.random() - 0.5) * 40, y: cy, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 2,
        w: 6 + Math.random() * 7, h: 9 + Math.random() * 9, r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.35,
        hue: HUES[i % HUES.length] + Math.random() * 18, life: 0, max: 140 + Math.random() * 70,
        shape: Math.random() < 0.25 ? 1 : 0, wob: Math.random() * 6
      });
    }
    if (!running) { running = true; requestAnimationFrame(tick); }
  }

  function tick() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    var alive = [];
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      p.life++;
      p.vy += 0.32; p.vx *= 0.985; p.vy *= 0.985;
      p.x += p.vx + Math.sin((p.life + p.wob * 10) / 9) * 0.8; p.y += p.vy; p.r += p.vr;
      var fade = Math.max(0, 1 - Math.max(0, p.life - p.max * 0.7) / (p.max * 0.3));
      if (p.life < p.max && p.y < innerHeight + 40) alive.push(p);
      ctx.save();
      ctx.globalAlpha = fade;
      ctx.translate(p.x, p.y);
      ctx.rotate(p.r);
      ctx.fillStyle = "hsl(" + p.hue + ",92%,58%)";
      if (p.shape) { ctx.beginPath(); ctx.arc(0, 0, p.w / 2, 0, Math.PI * 2); ctx.fill(); }
      else { ctx.scale(1, Math.cos(p.life / 6 + p.wob)); ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); }
      ctx.restore();
    }
    parts = alive;
    if (parts.length) requestAnimationFrame(tick);
    else { running = false; ctx.clearRect(0, 0, innerWidth, innerHeight); }
  }

  window.WornConfetti = { burst: burst };
})();
