"""Hand-authored SUGGESTED stroke order for Hindi (Devanagari), Arabic, Russian (print Cyrillic), Hebrew (block) and Greek.

Each character is a list of strokes, in writing order. A stroke is a string of points "x,y x,y ..." in a 100x100 box
(y down), written in the direction the pen moves. Points are joined with a smooth curve; "|" makes a sharp corner
(the next part starts at the previous point). Strokes are centerlines, not outlines.

   python3 content/tools/strokes_authored.py            -> writes content/strokes/{hindi,arabic,russian,hebrew,greek}/{hex}.svg
   python3 content/tools/strokes_authored.py --preview DIR   (needs Pillow) -> DIR/{lang}.png contact sheets:
        light grey = the real font glyph, colored strokes numbered at their start with an arrow at their end.

Output SVGs use viewBox 0 0 109 109 (the frame web/ and backend/worn/strokes.py read); the 100-box is centred in it
(+4.5 offset). Each file is labelled "suggested stroke order".
"""
import json, sys
from pathlib import Path

C = Path(__file__).resolve().parent.parent
OFF = 4.5

# ---------------------------------------------------------------- Russian (print lowercase)
RU = {
    "п": ["24,12 24,90", "24,16 | 76,16 | 76,90"],
    "р": ["29,12 29,92", "30,28 40,20 51,17 63,22 70,36 70,46 67,57 59,65 48,68 37,64 30,56"],
    "и": ["22,12 | 22,90 | 77,12 | 77,90"],
    "в": ["21,12 21,90",
          "21,15 | 50,15 63,19 68,29 64,40 50,48 | 21,48",
          "21,48 | 54,48 68,54 73,67 68,80 54,85 | 21,85"],
    "е": ["17,52 | 79,52 | 77,37 66,22 49,17 33,21 21,35 18,52 21,68 31,81 48,86 63,84 75,73"],
    "т": ["15,16 85,16", "50,16 50,90"],
    "с": ["72,32 64,19 50,15 35,18 26,30 24,50 26,70 35,82 50,85 64,81 72,68"],
    "а": ["21,30 28,21 40,16 52,16 61,24 62,36 | 62,82 66,88 78,88",
          "62,46 46,50 31,55 22,65 24,77 35,84 48,82 62,70"],
    "б": ["68,12 62,15 48,16 38,22 32,34 30,50 31,66 37,80 50,86 62,81 68,67 66,52 58,43 46,40 36,44 31,52"],
    "о": ["50,15 33,20 24,35 22,50 24,66 33,80 50,85 67,80 76,66 78,50 76,35 67,20 50,15"],
    "д": ["38,13 36,40 29,68", "38,13 | 66,13 | 66,68", "16,90 | 16,70 | 84,70 | 84,90"],
    "у": ["29,12 51,62", "78,12 60,52 48,76 40,86 30,89"],
    "г": ["31,12 31,90", "31,16 73,16"],
    "н": ["24,12 24,90", "75,12 75,90", "24,48 75,48"],
}

HI = {
    # body first, then vertical bars, then the headline (shirorekha); marks above the line come after it
    "न": ["26,61 21,53 23,45 | 58,44", "60,18 60,89", "15,15 82,15"],
    "म": ["33,17 | 33,66 26,63 23,56 26,51 33,52 | 65,52", "66,17 66,90", "11,15 87,15"],
    "स्ते": ["25,39 | 25,53 31,58 43,59 54,57", "12,57 23,70 33,84", "71,50 59,52 51,61 50,73 57,84",
            "74,38 74,86", "10,38 88,38", "58,16 66,27 72,37"],
    "ध": ["12,16 | 34,16 26,25 27,35 35,41 | 52,42", "34,42 26,52 27,63 35,71 48,73 61,69 70,60",
          "71,17 71,92", "56,16 90,16"],
    "न्य": ["17,58 13,52 15,47 | 46,47", "44,28 50,40 52,52 58,61 66,64 74,58", "75,26 75,77", "10,25 88,25"],
    "वा": ["37,35 28,41 23,51 25,61 32,68 42,68 49,62", "49,27 49,79", "72,27 72,79", "10,25 89,25"],
    "द": ["60,15 | 60,32 42,37 29,45 25,56 30,67 42,73 55,72 63,65 65,57 60,52", "56,72 66,80 76,87", "17,14 83,14"],
    "पा": ["20,26 20,46 26,56 38,58 49,52", "49,26 49,80", "72,26 72,80", "10,24 88,24"],
    "नी": ["18,70 13,63 16,58 | 41,58", "41,40 41,90", "64,40 64,90", "12,40 84,40", "64,40 63,24 57,14 48,13 42,19 40,27"],
    "दो": ["50,36 | 50,49 36,53 27,61 26,70 32,78 44,80 54,74 55,66 50,62", "50,75 57,82 63,88", "72,35 72,85",
          "15,35 87,35", "50,8 61,20 71,33"],
    "स्त": ["32,28 | 32,48 38,52 48,53 56,51", "14,47 24,59 34,73", "77,40 64,40 56,45 52,56 54,67 61,76",
           "77,27 77,75", "10,26 88,26"],
    "ए": ["33,17 | 33,47 45,58 57,69 65,79 66,88 62,93", "70,17 | 70,38 66,45 58,48", "13,16 87,16"],
    "क": ["40,38 28,42 22,52 25,63 35,68 46,62 50,55", "48,56 56,44 66,40 76,44 80,55 76,66 64,67",
          "48,22 48,82", "10,21 88,21"],
}
AR = {
    # isolated forms; main body first, dots after (right to left)
    "ا": ["52,12 48,88"],
    "ب": ["85,22 85,38 78,44 60,50 40,52 24,48 18,38 18,26", "49,73 51,77"],
    "ر": ["68,13 76,28 80,45 72,62 58,76 42,86 28,84 17,76"],
    "ح": ["21,24 32,17 52,18 | 69,15 | 50,24 36,36 29,52 32,68 42,82 56,88 70,84 80,76"],
    "م": ["34,36 40,22 50,12 60,20 70,33 54,36 34,36 | 36,56 39,72 40,88"],
    "ش": ["86,46 86,60 80,64 74,60 72,52 | 72,60 66,64 60,60 57,52 | 58,64 54,76 42,84 28,83 20,74 20,62 23,55",
          "71,31 72,32", "56,34 57,35", "64,21 65,22"],
    "ك": ["75,14 | 75,80 62,86 44,88 28,84 22,74 24,58", "52,41 46,51 53,56 44,62"],
    "ء": ["72,14 52,12 36,22 30,38 42,52 62,50 | 81,45 | 64,58 44,68 28,78 16,88"],
    "ص": ["47,37 50,48", "50,46 62,38 74,33 86,37 91,46 82,50 58,50 50,50 | 47,58 38,66 26,66 18,58 21,43"],
    "د": ["65,12 71,34 76,60 76,80 | 52,84 36,84 28,78 28,60"],
    "ي": ["82,14 70,14 57,24 52,36 64,43 78,48 76,59 58,66 38,70 26,64 22,48 24,32 30,19", "62,82 63,83", "45,82 46,83"],
    "ق": ["58,54 52,44 58,36 68,38 72,50 | 71,64 64,80 50,88 36,88 26,80 24,62", "66,17 67,18", "52,18 53,19"],
    "و": ["64,44 55,36 57,20 68,12 78,18 82,34 80,52 70,70 52,82 32,84 16,68"],
}

# ---------------------------------------------------------------- Hebrew (block print)
HE = {
    # frame first, then attached legs/arms; letters are read right to left but each stroke follows the pen
    "ש": ["17,16 17,40 20,58 30,74 50,80 68,74 78,56 82,36 83,16", "50,16 49,38 44,48 24,56"],
    "ל": ["33,10 | 33,37 | 66,37 | 66,52 60,64 55,74 55,90"],
    "ו": ["43,14 | 53,14 | 53,88"],                 # tall: a small head, then all the way down
    "ם": ["22,16 | 22,84 | 77,84 | 77,30 70,19 55,16 | 22,16"],
    "ת": ["14,17 | 50,15 70,18 79,28 83,45 83,88", "34,20 34,74 28,82 14,82"],
    "ד": ["14,16 86,16", "64,16 64,90"],
    "ה": ["15,18 | 50,15 66,20 74,32 76,50 76,90", "22,45 22,90"],
    "מ": ["14,12 22,27 30,42 | 21,89", "33,36 43,21 56,13 70,16 79,30 81,50 81,84 | 50,84"],
    "י": ["43,14 | 55,14 56,24 52,36 46,44"],      # small: only the top part (vs. ו, which goes down)
    "ח": ["22,17 22,90", "22,17 | 50,15 66,20 74,32 76,50 76,90"],
    "ב": ["15,17 | 48,15 62,18 70,28 72,45 72,84", "88,84 12,84"],
    "ר": ["18,17 | 50,15 66,20 74,32 75,50 75,89"],
    "א": ["20,10 48,48 80,90", "77,10 75,30 68,42 57,50", "36,42 26,52 21,70 19,90"],
}

# ---------------------------------------------------------------- Greek (lowercase print)
_TONOS = "57,11 49,30"  # the accent: last stroke, top right to bottom left
GR = {
    "γ": ["21,16 28,14 33,22 50,57 | 50,88", "73,12 50,57"],
    "ε": ["76,27 68,16 54,12 38,14 28,24 30,36 42,43 | 30,48 23,58 23,72 32,84 48,89 62,86 74,76"],
    "ι": ["45,12 45,78 50,86 58,87"],
    "α": ["74,30 64,16 50,12 36,16 26,30 22,50 25,70 36,85 50,88 63,80 73,62", "77,12 77,78 81,86 89,87"],
    "σ": ["88,17 | 50,17 34,22 22,38 21,56 28,74 42,85 58,85 72,74 78,56 75,36 63,22 50,17"],
    "ο": ["50,15 33,20 24,35 22,52 25,68 33,80 50,85 67,80 76,68 78,52 76,35 67,20 50,15"],
    "υ": ["24,12 24,55 28,72 38,82 50,85 62,82 72,72 76,55 76,12"],
    "χ": ["20,15 28,14 34,22 48,48 62,74 70,84 78,87", "72,12 25,88"],
    "ρ": ["28,90 | 29,40 33,24 44,14 56,12 68,18 74,34 71,52 60,63 46,64 31,56"],
    "τ": ["17,15 82,15", "50,15 50,80 54,86 62,87"],
    "ώ": ["34,39 27,52 26,68 31,80 40,85 47,80 50,66 50,52 | 50,66 54,80 61,85 70,80 75,68 74,52 67,39", _TONOS],
    "ν": ["23,12 48,86 | 80,12"],
    "ό": ["50,40 36,44 28,55 27,68 32,80 42,87 50,88 60,86 69,78 72,64 70,52 63,42 50,40", _TONOS],
    "φ": ["50,30 34,32 23,43 21,56 27,68 40,74 50,74 62,72 73,62 76,48 70,36 58,30 50,30", "50,12 50,88"],
    "ί": ["48,40 48,80 52,87 58,87", _TONOS],
    "λ": ["30,12 36,13 42,22 52,46 64,74 70,85 77,87", "48,40 22,88"],
    "ς": ["75,30 70,17 56,12 42,14 32,24 28,40 32,50 44,58 58,64 64,72 62,82 57,88"],
    "έ": ["70,48 63,41 52,39 40,42 34,50 37,58 46,62 | 36,66 29,72 28,82 36,89 50,91 62,88 71,79", _TONOS],
}


def _shift(table, dx=0.0, dy=0.0):
    """Move every point of every stroke (keeps '|' corners)."""
    def one(stroke):
        return " ".join(t if t == "|" else f"{float(t.split(',')[0]) + dx:g},{float(t.split(',')[1]) + dy:g}"
                        for t in stroke.split())
    return {ch: [one(s) for s in strokes] for ch, strokes in table.items()}


HI = _shift(HI, dx=4)  # Hindi was traced from a grid whose labels sit right of their lines (+4 fixes it)

LANGS = {"russian": RU, "hindi": HI, "arabic": AR, "hebrew": HE, "greek": GR}


# ---------------------------------------------------------------- geometry
def parse(stroke):
    parts, prev = [], None
    for chunk in stroke.split("|"):
        pts = [tuple(float(v) for v in p.split(",")) for p in chunk.split()]
        if prev is not None:
            pts = [prev] + pts
        if pts:
            prev = pts[-1]
        if len(pts) >= 2:
            parts.append(pts)
    return parts


def bezier(pts):
    """Catmull-Rom through pts -> list of cubic segments (p0, c1, c2, p1)."""
    segs, n = [], len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        segs.append((p1, c1, c2, p2))
    return segs


def path_d(stroke):
    f = lambda p: f"{p[0] + OFF:.1f},{p[1] + OFF:.1f}"
    out = []
    for i, part in enumerate(parse(stroke)):
        segs = bezier(part)
        if i == 0:
            out.append("M" + f(segs[0][0]))
        out += ["C" + " ".join(f(q) for q in s[1:]) for s in segs]
    return "".join(out)


def sample(stroke, k=24):
    pts = []
    for part in parse(stroke):
        for p0, c1, c2, p1 in bezier(part):
            for j in range(k + 1):
                t = j / k; u = 1 - t
                pts.append((u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0],
                            u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1]))
    return pts


def write_svgs():
    for lang, table in LANGS.items():
        d = C / "strokes" / lang
        d.mkdir(parents=True, exist_ok=True)
        keep = set()
        for ch, strokes in table.items():
            name = "-".join(f"{ord(c):x}" for c in ch)
            keep.add(name)
            paths = "".join(f'<path d="{path_d(s)}"/>' for s in strokes)
            (d / f"{name}.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 109 109">'
                f"<title>{ch}: suggested stroke order</title>"
                "<!-- Worn: hand-authored SUGGESTED stroke order (content/tools/strokes_authored.py), 100-box +4.5 -->"
                '<g fill="none" stroke="#000" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">'
                f"{paths}</g></svg>", encoding="utf-8")
        for f in d.glob("*.svg"):
            if f.stem not in keep:
                f.unlink(); print("pruned", f.relative_to(C))
        print(lang, len(table), "chars")


# ---------------------------------------------------------------- preview (authoring aid)
FONTS = {"hindi": "/System/Library/Fonts/Kohinoor.ttc", "arabic": "/System/Library/Fonts/GeezaPro.ttc",
         "russian": "/System/Library/Fonts/Helvetica.ttc", "hebrew": "/System/Library/Fonts/ArialHB.ttc",
         "greek": "/System/Library/Fonts/Helvetica.ttc"}
COLORS = [(230, 60, 60), (40, 140, 230), (30, 170, 90), (220, 140, 20), (150, 70, 200), (0, 170, 170), (200, 60, 150), (110, 110, 20)]


def preview(outdir, only=None):
    from PIL import Image, ImageDraw, ImageFont
    S, cellw = 4, 100 * 4 + 40
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    num = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    for lang, table in LANGS.items():
        if only and lang != only or not table:
            continue
        chars = list(table)
        cols = min(6, len(chars)); rows = (len(chars) + cols - 1) // cols
        W = Image.new("RGB", (cols * cellw, rows * (cellw + 30)), "white"); d = ImageDraw.Draw(W)
        for i, ch in enumerate(chars):
            ox, oy = (i % cols) * cellw + 20, (i // cols) * (cellw + 30) + 40
            d.text((ox, oy - 34), ch, fill="black", font=ImageFont.truetype(FONTS[lang], 26))
            f = ImageFont.truetype(FONTS[lang], 400)
            im = Image.new("L", (1400, 1000), 0); ImageDraw.Draw(im).text((300, 250), ch, font=f, fill=255)
            g = im.crop(im.getbbox()); k = 80 / max(g.width, g.height)
            g = g.resize((int(g.width * k * S), int(g.height * k * S)))
            W.paste(Image.new("RGB", g.size, (215, 215, 215)), (ox + (100 * S - g.width) // 2, oy + (100 * S - g.height) // 2), g)
            d.rectangle([ox, oy, ox + 100 * S, oy + 100 * S], outline=(200, 200, 255))
            for n, s in enumerate(table[ch]):
                col = COLORS[n % len(COLORS)]
                pts = [(ox + x * S, oy + y * S) for x, y in sample(s)]
                d.line(pts, fill=col, width=7, joint="curve")
                (x0, y0), (x1, y1) = pts[0], pts[-1]
                d.ellipse([x0 - 6, y0 - 6, x0 + 6, y0 + 6], fill=col)
                d.text((x0 + 8, y0 - 26), str(n + 1), fill=col, font=num)
                # arrowhead at the end, pointing along the last bit of the stroke
                px, py = next(((x, y) for x, y in reversed(pts) if (x - x1) ** 2 + (y - y1) ** 2 > 200), pts[0])
                vx, vy = x1 - px, y1 - py; L = (vx * vx + vy * vy) ** .5 or 1; vx, vy = vx / L, vy / L
                d.polygon([(x1 + vx * 12, y1 + vy * 12), (x1 - vy * 10, y1 + vx * 10), (x1 + vy * 10, y1 - vx * 10)], fill=col)
        W.save(outdir / f"{lang}.png")
        print("preview", outdir / f"{lang}.png")


if __name__ == "__main__":
    if "--preview" in sys.argv:
        i = sys.argv.index("--preview")
        preview(sys.argv[i + 1], sys.argv[i + 2] if len(sys.argv) > i + 2 else None)
    else:
        write_svgs()
