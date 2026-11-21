"""Synthesizes Worn's sound effects as WAVs (pure Python, no samples, no licenses needed: made here, CC0).
   python3 content/tools/make_sfx.py   -> content/sfx/*.wav  (22.05 kHz, mono, 16-bit)
"""
import math, random, struct, wave
from pathlib import Path

SR = 22050
OUT = Path(__file__).resolve().parent.parent / "sfx"
OUT.mkdir(exist_ok=True)
rnd = random.Random(7)  # deterministic: same files every run


def env(i, n, a=0.005, r=0.05):
    """attack/release envelope in seconds, to avoid clicks"""
    t, T = i / SR, n / SR
    return min(1.0, t / a if a else 1.0, (T - t) / r if r else 1.0)


def save(name, x, peak=0.85):
    m = max(1e-9, max(abs(v) for v in x))
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(v / m * peak * 32767)) for v in x))
    print(f"sfx/{name}.wav  {len(x) / SR:.2f}s")


def tone(freq_fn, dur, shape="sine", a=0.005, r=0.05, amp_fn=None):
    n, ph, out = int(dur * SR), 0.0, []
    for i in range(n):
        f = freq_fn(i / SR); ph += 2 * math.pi * f / SR
        if shape == "sine": v = math.sin(ph)
        elif shape == "square": v = 1.0 if math.sin(ph) >= 0 else -1.0
        elif shape == "saw": v = ((ph / (2 * math.pi)) % 1.0) * 2 - 1
        else: v = math.sin(ph) + 0.35 * math.sin(2 * ph) + 0.15 * math.sin(3 * ph)
        out.append(v * env(i, n, a, r) * (amp_fn(i / SR) if amp_fn else 1.0))
    return out


def mix(*tracks):
    n = max(len(t) + int(off * SR) for t, off in tracks); out = [0.0] * n
    for t, off in tracks:
        o = int(off * SR)
        for i, v in enumerate(t):
            out[o + i] += v
    return out


def lowpass(x, k=0.15):
    y, p = [], 0.0
    for v in x:
        p += k * (v - p); y.append(p)
    return y


# correct: bright two-note "ding-ding" (major third up)
save("ding", mix((tone(lambda t: 1318.5, 0.35, "rich", r=0.3, amp_fn=lambda t: math.exp(-6 * t)), 0),
                 (tone(lambda t: 1661.2, 0.55, "rich", r=0.45, amp_fn=lambda t: math.exp(-5 * t)), 0.11)))

# wrong: cartoon game-show buzzer (two detuned low squares, wobbly)
save("buzzer", lowpass([a + b for a, b in zip(
    tone(lambda t: 110 + 4 * math.sin(2 * math.pi * 9 * t), 0.6, "square", r=0.08),
    tone(lambda t: 116, 0.6, "square", r=0.08))], 0.3), peak=0.6)

# close: springy "boing" (pitch drops with a fast wobble)
save("boing", tone(lambda t: 220 + 260 * math.exp(-7 * t) + 30 * math.sin(2 * math.pi * 14 * t) * math.exp(-3 * t),
                   0.7, "sine", r=0.2, amp_fn=lambda t: math.exp(-2.5 * t)))

# close (alt): "whoops" slide down
save("slide", tone(lambda t: 700 * math.exp(-2.2 * t) + 180, 0.5, "rich", r=0.15, amp_fn=lambda t: 1 - t))

# streak/milestone build-up: snare drumroll, crescendo, then a cymbal-ish crash
roll, n = [], int(1.4 * SR)
for i in range(n):
    t = i / SR
    hit = (t * 34) % 1.0                               # 34 hits per second, alternating sticks
    stick = 1.0 if int(t * 34) % 2 == 0 else 0.8
    snare = rnd.uniform(-1, 1) * (math.exp(-hit * 3.5) * 0.8 + 0.2)   # hits overlap into a roll
    roll.append(snare * stick * (0.2 + 0.8 * (t / 1.4) ** 1.5))       # crescendo
crash = [rnd.uniform(-1, 1) * math.exp(-3.2 * i / SR) for i in range(int(1.0 * SR))]
crash = [a - b for a, b in zip(crash, lowpass(crash, 0.25))]    # keep the hiss, lose the thud
save("drumroll", mix((roll, 0), (crash, 1.4)), peak=0.7)

# milestone: "ta-da" fanfare (C-E-G then a long C)
notes = [(523.3, 0.0, 0.14), (659.3, 0.12, 0.14), (784.0, 0.24, 0.14), (1046.5, 0.38, 0.8)]
save("tada", mix(*[(tone(lambda t, f=f: f * (1 + 0.004 * math.sin(2 * math.pi * 6 * t)), d, "saw", r=min(0.3, d / 2),
                         amp_fn=lambda t: 0.8), o) for f, o, d in notes]), peak=0.6)

# cheer: crowd-ish noise swell plus a happy arpeggio on top
noise = lowpass([rnd.uniform(-1, 1) for _ in range(int(1.6 * SR))], 0.08)
swell = [v * math.sin(math.pi * i / len(noise)) ** 0.6 for i, v in enumerate(noise)]
arp = [(tone(lambda t, f=f: f, 0.25, "sine", r=0.2, amp_fn=lambda t: 0.35 * math.exp(-4 * t)), o)
       for f, o in ((784, 0.1), (988, 0.22), (1175, 0.34), (1568, 0.46), (1175, 0.7), (1568, 0.82))]
save("cheer", mix((swell, 0), *arp), peak=0.7)

# sparkle: random high glassy pings, decaying
pings = [(tone(lambda t, f=f: f, 0.35, "sine", r=0.3, amp_fn=lambda t: math.exp(-12 * t) * 0.6), o)
         for f, o in ((rnd.uniform(2200, 4200), rnd.uniform(0, 0.55)) for _ in range(14))]
save("sparkle", mix(*pings))

# chef's kiss: a quick lip "pop" then a tiny high ding
pop = [rnd.uniform(-1, 1) * math.exp(-60 * i / SR) for i in range(int(0.08 * SR))]
save("kiss", mix((lowpass(pop, 0.35), 0), (tone(lambda t: 2093, 0.3, "sine", r=0.25, amp_fn=lambda t: 0.5 * math.exp(-8 * t)), 0.07)))
