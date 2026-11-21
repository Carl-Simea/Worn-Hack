"""Simulate the glasses + iPhone against a REAL Worn backend, so /live can be tested without hardware (owner: agent B).

It posts exactly what the iOS app reports (/event glasses.status, glasses.show, ink, grade.start, confetti),
sends a rendered "handwriting" photo to /stroke-match per stroke and to /grade at the end, then /session/next.

  uv run --with pillow python web/dev/sim_glasses.py http://127.0.0.1:8000 --lang mandarin --item hello [--chars 2] [--wrong]

Don't run it against the live demo server while someone is presenting: it starts lessons.
"""
import argparse, io, json, random, sys, time, urllib.request, uuid

from PIL import Image, ImageDraw, ImageFont

FONTS = {
    "mandarin": "/System/Library/Fonts/STHeiti Medium.ttc",
    "hindi": "/System/Library/Fonts/Kohinoor.ttc",
    "arabic": "/System/Library/Fonts/GeezaPro.ttc",
    "hebrew": "/System/Library/Fonts/ArialHB.ttc",
    "russian": "/System/Library/Fonts/Helvetica.ttc",
    "greek": "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
}


def call(base, method, path, body=None, form=None):
    data, headers = None, {}
    if body is not None:
        data, headers = json.dumps(body).encode(), {"Content-Type": "application/json"}
    if form is not None:
        b = uuid.uuid4().hex
        parts = []
        for k, v in form.items():
            if isinstance(v, bytes):
                parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="p.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode() + v + b"\r\n")
            else:
                parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        data = b"".join(parts) + f"--{b}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={b}"}
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:200]}


def event(base, t, **data):
    call(base, "POST", "/event", {"type": t, "data": data})


def photo(lang, ch, wrong=False):
    im = Image.new("RGB", (1024, 768), (238, 233, 220))
    d = ImageDraw.Draw(im)
    d.rectangle((262, 134, 762, 634), outline=(200, 186, 160), width=4)
    try:
        f = ImageFont.truetype(FONTS.get(lang, FONTS["russian"]), 380 if len(ch) == 1 else int(900 / max(2, len(ch))))
    except OSError:
        f = ImageFont.load_default()
    text = "X" if wrong else ch
    box = d.textbbox((0, 0), text, font=f)
    d.text((512 - (box[0] + box[2]) / 2, 384 - (box[1] + box[3]) / 2), text, font=f, fill=(28, 32, 44))
    im = im.rotate(random.uniform(-4, 4), fillcolor=(120, 110, 95))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=88)
    return out.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--lang", default="mandarin")
    ap.add_argument("--item", default="hello")
    ap.add_argument("--chars", type=int, default=99)
    ap.add_argument("--wrong", action="store_true", help="first attempt is wrong (shows the retry path)")
    ap.add_argument("--pace", type=float, default=0.9, help="seconds per stroke")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    event(base, "app.open", demo_mode=False)
    event(base, "glasses.status", connected=True, status="Connected")
    s = call(base, "POST", "/session", {"lang": a.lang, "item_id": a.item, "char_index": 0, "mode": "write"})
    if "error" in s:
        sys.exit(f"session failed: {s}")
    event(base, "practice.start", mode="write")
    done = 0
    wrong = a.wrong
    while done < a.chars:
        ch, n = s["char"], s.get("stroke_count") or 1
        print(f"{s['lang']} {ch} ({s['char_index'] + 1}/{s['total_chars']}), {n} strokes")
        time.sleep(2.0)  # watch the animation
        img = photo(s["lang"], ch, wrong)
        for k in range(n):
            event(base, "glasses.show", phase="write", stroke=k, stroke_count=n)
            time.sleep(a.pace)
            event(base, "ink", new_ink=round(random.uniform(.03, .12), 3), tier1_ms=random.randint(12, 40))
            r = call(base, "POST", "/stroke-match", form={"image": img, "char": ch, "stroke_index": str(k), "lang": s["lang"]})
            print("   stroke", k + 1, r.get("score", r))
        event(base, "grade.start", char=ch)
        g = call(base, "POST", "/grade", form={"image": img, "char": ch, "lang": s["lang"]})
        print("   grade", {k: g.get(k) for k in ("correct", "score", "feedback", "reaction", "mood")})
        if g.get("correct"):
            event(base, "confetti", char=ch)
        time.sleep(4.0)
        if wrong:
            wrong = False
            continue  # same char again, written right
        done += 1
        if s["char_index"] + 1 >= s["total_chars"] or done >= a.chars:
            break
        nxt = call(base, "POST", "/session/next")
        s = nxt if "char" in nxt else call(base, "POST", "/session", {"lang": s["lang"], "item_id": s["item_id"], "char_index": s["char_index"] + 1})
    event(base, "practice.stop", done=done)


if __name__ == "__main__":
    main()
