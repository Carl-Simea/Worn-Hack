"""End-to-end click-through of /app (and /live reacting to it) against a running backend or the mock.

  uv run --with playwright python web/dev/e2e_app.py http://127.0.0.1:8092 [--photo path.jpg]

Starts lessons, so don't point it at the demo while someone is presenting.
"""
import io, json, sys, time, urllib.request
from playwright.sync_api import sync_playwright, expect

base = sys.argv[1].rstrip("/")
photo = sys.argv[sys.argv.index("--photo") + 1] if "--photo" in sys.argv else None
fails, errs = [], []


def api(path):
    return json.load(urllib.request.urlopen(base + path))


def check(name, fn):
    try:
        fn()
        print("PASS", name)
    except Exception as e:
        fails.append(name)
        print("FAIL", name, "-", str(e).splitlines()[0][:200])


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    ctx = b.new_context(viewport={"width": 1180, "height": 820})
    pg = ctx.new_page()
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/app")
    expect(pg.locator(".lang").first).to_be_visible(timeout=8000)

    def start_lesson():
        pg.locator('.lang[data-lang="mandarin"]').click()
        expect(pg.locator("#v-lang")).to_be_visible()
        pg.locator(".item").first.click()
        expect(pg.locator("#v-practice")).to_be_visible()
        expect(pg.locator("#pWord .cur")).to_have_text("你", timeout=5000)
        s = api("/session")
        assert s["lang"] == "mandarin" and s["char_index"] == 0, s
    check("pick Mandarin > hello starts a session on the backend", start_lesson)

    def stroke_anim():
        pg.wait_for_timeout(1500)
        assert pg.locator("#pInk svg path").count() > 3
        assert "stroke" in pg.locator("#pLabel").inner_text()
    check("practice shows the stroke animation", stroke_anim)

    def grade_photo():
        f = photo
        if not f:
            from PIL import Image
            f = "/tmp/worn-e2e.jpg"
            Image.new("RGB", (640, 480), "white").save(f)
        pg.set_input_files("#cam", f)
        pg.wait_for_function("document.getElementById('res').className.match(/\\b(ok|no)\\b/)", timeout=60000)
        assert pg.locator("#resSc").inner_text().strip().startswith(tuple("0123456789")), pg.locator("#resSc").inner_text()
    check("phone camera photo is graded and shown", grade_photo)

    def next_char():
        pg.locator("#next").click()
        pg.wait_for_function("document.querySelector('#pWord .cur') && document.querySelector('#pWord .cur').textContent === '好'", timeout=6000)
        assert api("/session")["char_index"] == 1
    check("Next moves to the second character", next_char)

    def dictation():
        pg.goto(base + "/app#/lang/russian")
        pg.locator('#modeSeg button[data-m="dictation"]').click()
        pg.locator(".item").nth(1).click()
        expect(pg.locator("#stage.dictation")).to_be_visible(timeout=5000)
        assert api("/session")["mode"] == "dictation"
    check("dictation hides the character", dictation)

    def compose():
        pg.goto(base + "/app#/compose")
        pg.fill("#cText", "thank you")
        pg.locator("#cLangs .chip", has_text="Hebrew").click()
        pg.locator("#cGo").click()
        expect(pg.locator("#cWrite")).to_be_enabled(timeout=60000)
        assert pg.locator("#cNative").inner_text().strip()
        pg.locator("#cWrite").click()
        expect(pg.locator("#v-practice")).to_be_visible(timeout=60000)
        s = api("/session")
        assert s["lang"] == "hebrew" and s["mode"] == "compose", s
    check("help me write: compose then practice it", compose)

    def name():
        pg.goto(base + "/app#/name")
        pg.fill("#nText", "Maya")
        pg.locator("#nGo").click()
        expect(pg.locator(".ncard .n").first).to_be_visible(timeout=60000)
        n = pg.locator(".ncard .n").count()
        assert n >= 4, n
        pg.locator(".ncard").first.click()
        pg.wait_for_timeout(800)
        assert pg.locator(".ncard.tracing svg").count() == 1
    check("write your name: 5 scripts, tap to trace", name)

    def daily():
        pg.goto(base + "/app#/daily")
        expect(pg.locator(".ditem").first).to_be_visible(timeout=8000)
        pg.locator("#dStart").click()
        expect(pg.locator("#pDaily")).to_be_visible(timeout=6000)
        assert "1 of" in pg.locator("#pDaily").inner_text()
        pg.locator("#next").click()
        pg.wait_for_function("document.getElementById('pDaily').textContent.indexOf('2 of') >= 0", timeout=6000)
    check("Daily 5 runs through its list", daily)

    def live_follows():
        lv = ctx.new_page()
        lv.on("console", lambda m: errs.append("live: " + m.text) if m.type == "error" else None)
        lv.goto(base + "/live")
        s = api("/session")
        lv.wait_for_function(f"document.querySelector('#chars .cur') && document.querySelector('#chars .cur').textContent === {json.dumps(s['char'])}", timeout=6000)
        lv.close()
    check("/live shows the same lesson (handoff)", live_follows)
    b.close()

real = [e for e in errs if "favicon" not in e]
print("console errors:", len(real))
for e in real[:10]:
    print("   ", e[:200])
print("RESULT:", "ALL PASS" if not fails and not real else f"{len(fails)} failed, {len(real)} console errors")
sys.exit(1 if fails or real else 0)
