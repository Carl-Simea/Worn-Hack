"""Headless check of Worn web pages: screenshots + console errors + horizontal overflow.

  uv run --with playwright python web/dev/shoot.py http://127.0.0.1:8000 /live /app ... [--out screenshots/web] [--wait 2500]

Sizes: phone 390x844, ipad 1180x820, laptop 1440x900 (glasses pages are always 640x480).
Exit code 1 if any page logs a console error, throws, or scrolls sideways.
"""
import argparse, os, re, sys
from playwright.sync_api import sync_playwright

SIZES = {"phone": (390, 844), "ipad": (1180, 820), "laptop": (1440, 900)}

ap = argparse.ArgumentParser()
ap.add_argument("base"); ap.add_argument("paths", nargs="+")
ap.add_argument("--out", default="screenshots/web"); ap.add_argument("--wait", type=int, default=2500)
ap.add_argument("--sizes", default="phone,ipad,laptop"); ap.add_argument("--dark", action="store_true")
ap.add_argument("--full", action="store_true", help="full-page screenshots")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
bad = 0
with sync_playwright() as p:
    try:
        b = p.chromium.launch(channel="chrome")
    except Exception:
        b = p.chromium.launch()
    for path in a.paths:
        glasses = path.startswith("/glasses")
        sizes = {"glasses": (640, 480)} if glasses else {k: SIZES[k] for k in a.sizes.split(",")}
        for name, (w, h) in sizes.items():
            ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=2 if name != "glasses" else 1,
                                color_scheme="dark" if a.dark else "light")
            pg = ctx.new_page()
            errs = []
            pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
            pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
            pg.on("requestfailed", lambda r: errs.append(f"requestfailed: {r.url} {r.failure}"))
            pg.on("response", lambda r: errs.append(f"http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else None)
            pg.goto(a.base + path, wait_until="load")
            pg.wait_for_timeout(a.wait)
            over = pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") or "root"
            f = f"{a.out}/{slug}-{name}{'-dark' if a.dark else ''}.png"
            pg.screenshot(path=f, full_page=a.full)
            real = [e for e in errs if "favicon" not in e]
            status = "OK " if not real and over <= 0 else "BAD"
            if status == "BAD": bad += 1
            print(f"{status} {path} {name} overflow={over} -> {f}")
            for e in real: print("     ", e[:300])
            ctx.close()
    b.close()
sys.exit(1 if bad else 0)
