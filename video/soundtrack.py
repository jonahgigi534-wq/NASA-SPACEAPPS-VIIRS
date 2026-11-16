"""
Synthesized soundtrack for the demo reel (no samples, no AI voice): music bed + sound effects
timed to the scenes in video/reel.html. If you change timings there, change them here too.

    python video/soundtrack.py          # -> video/out/soundtrack.wav (48 kHz stereo, 29 s)
"""

import wave
from pathlib import Path

import numpy as np

SR = 48000
DUR = 29.0
OUT = Path(__file__).resolve().parent / "out" / "soundtrack.wav"
rng = np.random.default_rng(3)
N = int(SR * DUR)
L = np.zeros(N)
R = np.zeros(N)


def note(f):                                   # "A3" -> Hz
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    n = names[f[0]] + (1 if "#" in f else 0) + 12 * (int(f[-1]) - 4)
    return 440.0 * 2 ** (n / 12)


def env(n, a, d, sustain=1.0, r=0.0):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4))
    if r:
        e *= np.clip((n / SR - t) / r, 0, 1)
    return e * (sustain + (1 - sustain) * np.exp(-t / max(d, 1e-4)))


def add(sig, t0, gain=1.0, pan=0.0):
    i = int(t0 * SR)
    if i >= N:
        return
    sig = sig[: N - i]
    L[i:i + len(sig)] += sig * gain * (1 - max(0, pan))
    R[i:i + len(sig)] += sig * gain * (1 + min(0, pan))


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):               # one-pole, fine for short buffers
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def lowpass_fast(x, cutoff, passes=2):
    k = max(1, int(SR / cutoff / 2))
    for _ in range(passes):
        x = np.convolve(x, np.ones(k) / k, mode="same")
    return x


# ---------------------------------------------------------------- music bed: pad chords
def pad(freqs, length, gain):
    n = int(length * SR)
    t = np.arange(n) / SR
    s = np.zeros(n)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):                       # detuned saw-ish stack
            ff = f * 2 ** (det / 12)
            s += sum(np.sin(2 * np.pi * ff * k * t) / k for k in range(1, 6))
    s = lowpass_fast(s, 1400)
    return s * env(n, 0.9, 1, 1, 1.2) * gain / len(freqs)


CHORDS = [  # (start, length, notes)
    (0.0, 3.2, ["A2", "E3", "A3", "C4"]),
    (3.0, 4.4, ["F2", "C3", "A3", "C4"]),
    (7.3, 2.4, ["C3", "G3", "C4", "E4"]),
    (9.5, 2.2, ["G2", "D3", "B3", "D4"]),
    (11.5, 3.0, ["A2", "E3", "C4", "E4"]),
    (14.3, 3.4, ["F2", "C3", "A3", "E4"]),
    (17.6, 3.6, ["C3", "G3", "C4", "E4"]),
    (21.1, 2.2, ["G2", "D3", "B3", "D4"]),
    (23.2, 3.3, ["A2", "E3", "C4", "E4"]),
    (26.4, 2.6, ["F2", "C3", "A3", "C4", "G4"]),
]
for t0, ln, ns in CHORDS:
    p = pad([note(x) for x in ns], ln + 1.0, 0.16)
    add(p, t0, 1.0, -0.15)
    add(p, t0 + 0.012, 1.0, 0.15)


# ---------------------------------------------------------------- pulse (100 bpm 8ths) from 3.0 s
def pluck(f, length=0.25, bright=6, gain=1.0):
    n = int(length * SR)
    t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * f * k * t) * np.exp(-t * (8 + 6 * k)) / k for k in range(1, bright))
    return s * gain


bass_roots = {0: "A1", 3.0: "F1", 7.3: "C2", 9.5: "G1", 11.5: "A1", 14.3: "F1", 17.6: "C2", 21.1: "G1", 23.2: "A1", 26.4: "F1"}
roots = sorted(bass_roots.items())
beat = 0.3
t = 3.0
while t < 26.4:
    if not (9.4 < t < 11.5):                               # breathe during the logo
        root = [r for s, r in roots if s <= t][-1]
        add(pluck(note(root), 0.28, 4, 0.5), t, 0.55 if int(round((t - 3) / beat)) % 2 == 0 else 0.3)
    t += beat


# ---------------------------------------------------------------- effects
def noise(n):
    return rng.standard_normal(n)


def whoosh(length=0.6, gain=0.25):
    n = int(length * SR)
    x = noise(n)
    tt = np.arange(n) / SR
    out = np.zeros(n)
    # sweep: blend lowpassed versions, rising then falling brightness
    lo, hi = lowpass_fast(x, 600), lowpass_fast(x, 4000)
    mix = np.sin(np.pi * tt / length)
    out = lo * (1 - mix) + hi * mix
    return out * np.sin(np.pi * tt / length) ** 2 * gain


def boom(gain=0.9, f0=70, length=1.4):
    n = int(length * SR)
    tt = np.arange(n) / SR
    f = f0 * (1 + 1.5 * np.exp(-tt * 18))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 3.2)
    s += lowpass_fast(noise(n), 900) * np.exp(-tt * 14) * 0.6
    return s * gain


def riser(length=1.0, gain=0.25):
    n = int(length * SR)
    tt = np.arange(n) / SR
    f = 200 * 2 ** (tt / length * 2.5)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.3 + lowpass_fast(noise(n), 3000) * 0.7
    return s * (tt / length) ** 2 * gain


def click(gain=0.35):
    n = int(0.05 * SR)
    tt = np.arange(n) / SR
    return (np.sin(2 * np.pi * 2400 * tt) * 0.6 + noise(n) * 0.4) * np.exp(-tt * 140) * gain


def tick(f=1800, gain=0.12):
    n = int(0.06 * SR)
    tt = np.arange(n) / SR
    return np.sin(2 * np.pi * f * tt) * np.exp(-tt * 90) * gain


def shimmer(length=1.6, gain=0.18):
    n = int(length * SR)
    tt = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * note(x) * tt + i) for i, x in enumerate(["E5", "G5", "B5", "D6", "E6"]))
    return s * np.exp(-tt * 2.2) * (1 - np.exp(-tt * 40)) * gain / 5


# hook: number count-up ticks, pop
for i in range(14):
    add(tick(1200 + i * 90, 0.09), 0.55 + 1.2 * (1 - (1 - i / 14) ** 2.2))
add(boom(0.55, 62, 1.2), 0.45)
add(whoosh(0.7, 0.22), 2.6)
# chart: bars
for i in range(11):
    add(pluck(note("A4") * 2 ** (i / 24), 0.18, 3, 0.18), 3.3 + i * 0.075, 1, -0.3 + i * 0.05)
for k in range(14):
    add(pluck(note("E5") * 2 ** (k / 30), 0.16, 5, 0.16), 4.6 + k * 0.05, 1, -0.2 + k * 0.04)
add(boom(0.35, 90, 0.8), 4.6)
add(riser(1.0, 0.18), 6.35)
add(boom(0.75, 58, 1.6), 7.35)
add(shimmer(1.4, 0.16), 7.4)
add(whoosh(0.7, 0.22), 9.2)
# logo
add(riser(0.8, 0.14), 9.65)
add(boom(0.85, 52, 1.8), 10.45)
add(shimmer(2.0, 0.22), 10.45)
# app
add(whoosh(0.9, 0.28), 11.3)
add(click(0.4), 12.65)
add(click(0.4), 14.05)
for k in range(12):
    add(tick(1500 + 40 * (k % 4), 0.1), 14.3 + k * 0.265, 1, 0.2)
for t0 in (17.45, 21.0, 23.1, 25.15):
    add(whoosh(0.5, 0.16), t0)
add(tick(2200, 0.12), 18.0)
add(tick(2200, 0.12), 19.8)
for k in range(3):
    add(click(0.25), 25.45 + k * 0.3)
# end
add(whoosh(0.8, 0.25), 26.15)
add(boom(0.8, 55, 2.2), 26.5)
add(shimmer(2.2, 0.2), 26.55)

# ---------------------------------------------------------------- master
mix = np.stack([L, R], axis=1)
t = np.arange(N) / SR
fade = np.clip(t / 0.15, 0, 1) * np.clip((DUR - t) / 0.6, 0, 1)
mix *= fade[:, None]
mix = np.tanh(mix * 1.4) / np.tanh(1.4)               # soft limiter
mix *= 0.89 / np.max(np.abs(mix))                      # about -1 dBFS peak
OUT.parent.mkdir(exist_ok=True)
with wave.open(str(OUT), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype(np.int16).tobytes())
print("wrote", OUT, f"{DUR:.1f} s")
