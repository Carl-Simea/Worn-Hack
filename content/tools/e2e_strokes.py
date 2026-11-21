"""End-to-end content check against a backend: for every item of every language, start a session and check its
stroke_url, stroke_count and audio. Then "write" each character stroke by stroke (the template itself, drawn as
dark marker ink on white paper) and send each stage to POST /stroke-match, which is the tier-2 auto-grade the
glasses use.
   uv run --with pillow python content/tools/e2e_strokes.py http://127.0.0.1:8010
Run it on a private backend: it changes the session. Prints one pass/fail line per language.
"""
import io
import json
import re
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from PIL import Image, ImageDraw

C = Path(__file__).resolve().parent.parent
BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010").rstrip("/")
LANGS = ["mandarin", "hindi", "arabic", "russian", "hebrew", "greek"]
NUM = re.compile(r"-?\d+(?:\.\d+)?")
S = 480
CHAR = float(__import__("os").environ.get("CHAR", "0.5"))   # the character fills half the photo, like a 3 cm box seen by the glasses camera


def place(x, y):
    return (S * (1 - CHAR) / 2 + x * CHAR, S * (1 - CHAR) / 2 + y * CHAR)


def req(method, path, body=None, headers=None):
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=30) as f:
        return f.status, f.read()


def post_json(path, obj):
    st, b = req("POST", path, json.dumps(obj).encode(), {"content-type": "application/json"})
    return json.loads(b)


def cubic(p0, p1, p2, p3, n=16):
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        yield (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])


def svg_strokes(text):
    out = []
    for d in re.findall(r'<path[^>]* d="([^"]+)"', text):
        pts, cur = [], None
        for cmd, args in re.findall(r"([MLC])([^MLC]*)", d):
            v = [float(x) for x in NUM.findall(args)]
            pairs = list(zip(v[0::2], v[1::2]))
            if cmd == "M":
                cur = pairs[0]; pts.append(cur); pairs = pairs[1:]; cmd = "L"
            if cmd == "L":
                for p in pairs:
                    pts.append(p); cur = p
            elif cmd == "C":
                for i in range(0, len(pairs) - 2, 3):
                    seg = list(cubic(cur, pairs[i], pairs[i + 1], pairs[i + 2]))
                    pts += seg[1:]; cur = pairs[i + 2]
        out.append([place(x / 109 * S, y / 109 * S) for x, y in pts])
    return out


def hanzi_strokes(d):
    # hanzi-writer: 1024 box, y up, baseline offset 900
    return [[place(x / 1024 * S, (900 - y) / 1024 * S) for x, y in m] for m in d["medians"]]


def render(strokes):
    im = Image.new("L", (S, S), 245)
    dr = ImageDraw.Draw(im)
    for st in strokes:
        if len(st) == 1:
            x, y = st[0]; dr.ellipse((x - 4, y - 4, x + 4, y + 4), fill=25)
        else:
            dr.line(st, fill=25, width=8, joint="curve")
            for x, y in (st[0], st[-1]):
                dr.ellipse((x - 4, y - 4, x + 4, y + 4), fill=25)
    b = io.BytesIO(); im.convert("RGB").save(b, "JPEG", quality=90); return b.getvalue()


def stroke_match(img, ch, k, lang):
    bd = uuid.uuid4().hex
    parts = []
    for name, val in (("char", ch), ("stroke_index", str(k)), ("lang", lang)):
        parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{val}\r\n'.encode())
    parts.append(f'--{bd}\r\nContent-Disposition: form-data; name="image"; filename="p.jpg"\r\n'
                 f"Content-Type: image/jpeg\r\n\r\n".encode() + img + b"\r\n")
    parts.append(f"--{bd}--\r\n".encode())
    st, b = req("POST", "/stroke-match", b"".join(parts), {"content-type": f"multipart/form-data; boundary={bd}"})
    return json.loads(b)


def load_strokes(lang, ch):
    stem = "-".join(f"{ord(x):x}" for x in ch)
    if lang == "mandarin":
        return hanzi_strokes(json.loads(req("GET", f"/static/content/strokes/{lang}/{stem}.json")[1]))
    return svg_strokes(req("GET", f"/static/content/strokes/{lang}/{stem}.svg")[1].decode())


def main():
    summary = []
    detail = []
    for lang in LANGS:
        L = json.loads((C / f"{lang}.json").read_text(encoding="utf-8"))
        fails, chars_ok, chars_n, scores = [], 0, 0, []
        for it in L["phrases"]:
            for ci, ch in enumerate(it["chars"]):
                chars_n += 1
                try:
                    s = post_json("/session", {"lang": lang, "item_id": it["id"], "char_index": ci, "mode": "write"})
                except Exception as e:
                    fails.append(f"{it['id']}[{ci}] {ch}: /session {e}"); continue
                url, n = s.get("stroke_url"), s.get("stroke_count") or 0
                if s.get("char") != ch or not url or n < 1:
                    fails.append(f"{it['id']}[{ci}] {ch}: session char={s.get('char')!r} url={url} n={n}"); continue
                st, body = req("GET", urllib.parse.quote(url))
                if url.endswith(".json"):
                    strokes = hanzi_strokes(json.loads(body))
                else:
                    strokes = svg_strokes(body.decode())
                if len(strokes) != n:
                    fails.append(f"{it['id']}[{ci}] {ch}: file has {len(strokes)} strokes, session says {n}")
                if ci == 0 and s.get("audio_url"):
                    a_st, a = req("GET", urllib.parse.quote(s["audio_url"]))
                    if a_st != 200 or len(a) < 2000:
                        fails.append(f"{it['id']}: audio {s['audio_url']} {a_st} {len(a)} bytes")
                ok_all, last = True, None
                for k in range(len(strokes)):
                    r = stroke_match(render(strokes[:k + 1]), ch, k, lang)
                    last = r
                    scores.append(r.get("score") or 0)
                    if (r.get("score") or 0) < 40:
                        ok_all = False
                        detail.append(f"  {lang} {ch} stroke {k + 1}/{len(strokes)}: score {r.get('score')} "
                                      f"hint={r.get('hint')!r}")
                if last is not None and not last.get("char_done"):
                    detail.append(f"  {lang} {ch}: last stroke score {last.get('score')}, char_done=false")
                    ok_all = False
                chars_ok += ok_all
                if not ok_all:
                    fails.append(f"{it['id']}[{ci}] {ch}: tier-2 match low")
        # Negative check: write another item's character in full; the target must NOT be "done".
        wrong_ok, wrong_n = 0, 0
        all_chars = [c for it in L["phrases"] for c in it["chars"] if len(c) == 1 or lang == "hindi"]
        for a, b in zip(all_chars, all_chars[1:] + all_chars[:1]):
            if a == b:
                continue
            other = load_strokes(lang, b)
            n_a = len(load_strokes(lang, a))
            r = stroke_match(render(other), a, n_a - 1, lang)
            wrong_n += 1
            if not r.get("char_done"):
                wrong_ok += 1
            else:
                detail.append(f"  {lang}: writing {b} was accepted as {a} (score {r.get('score')})")
        avg = sum(scores) / max(1, len(scores))
        summary.append(f"{'PASS' if not fails else 'FAIL'}  {L['name']:<17} {chars_ok}/{chars_n} chars accepted "
                       f"stroke by stroke, avg stroke score {avg:.0f}; wrong letter rejected {wrong_ok}/{wrong_n}" + ("" if not fails else f"  ({len(fails)} issues)"))
        detail += [f"  {lang}: {f}" for f in fails]
    print("\n".join(detail))
    print("\n".join(summary))
    return 0 if all(s.startswith("PASS") for s in summary) else 1


if __name__ == "__main__":
    sys.exit(main())
