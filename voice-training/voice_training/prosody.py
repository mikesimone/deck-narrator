"""Prosody measurements for one utterance and real-vs-generated comparisons.

analyze(): speaking rate (syllables/s over the trimmed utterance), pauses (silences >= 150 ms inside it),
F0 via WORLD harvest in semitones re 100 Hz (mean, std, 5-95 % range) and the F0 contour.
compare(): per-pair differences plus a DTW distance between mean-removed F0 contours (intonation shape).
"""
import re
import numpy as np, librosa, pyworld

SR, HOP = 16000, 0.01

def syllables(text):
    n = 0
    for w in re.findall(r"[a-z']+|\d+(?:\.\d+)?", text.lower()):
        if w[0].isdigit():  # rough: spoken numbers average ~1.5 syllables per digit group character
            n += max(1, round(1.5 * len(w.replace(".", ""))))
            continue
        w = re.sub(r"e$", "", w) if len(w) > 3 else w
        n += max(1, len(re.findall(r"[aeiouy]+", w)))
    return n

def analyze(path, text):
    y = librosa.load(path, sr=SR)[0]
    y, _ = librosa.effects.trim(y, top_db=35)
    dur = len(y) / SR
    rms = librosa.feature.rms(y=y, frame_length=400, hop_length=160)[0]
    db = 20 * np.log10(rms + 1e-9); silent = db < db.max() - 35
    pauses, run = [], 0
    for s in silent:
        if s: run += 1
        else:
            if run * HOP >= 0.15: pauses.append(run * HOP)
            run = 0
    f0, t = pyworld.harvest(y.astype(np.float64), SR, f0_floor=60, f0_ceil=400, frame_period=HOP * 1000)
    st = np.where(f0 > 0, 12 * np.log2(np.maximum(f0, 1) / 100), np.nan)
    v = st[~np.isnan(st)]
    return dict(dur=dur, rate=syllables(text) / dur, n_pauses=len(pauses), pause_per_s=len(pauses) / dur,
                pause_mean=float(np.mean(pauses)) if pauses else 0.0,
                f0_mean=float(np.mean(v)) if len(v) else np.nan, f0_std=float(np.std(v)) if len(v) else np.nan,
                f0_range=float(np.percentile(v, 95) - np.percentile(v, 5)) if len(v) else np.nan,
                contour=st)

def _interp(c):
    idx = np.arange(len(c)); ok = ~np.isnan(c)
    if ok.sum() < 2: return None
    c = np.interp(idx, idx[ok], c[ok])[::2]  # 20 ms
    return c - c.mean()

def dtw(c1, c2):
    a, b = _interp(c1), _interp(c2)
    if a is None or b is None: return np.nan
    D, wp = librosa.sequence.dtw(X=a[None], Y=b[None], metric="cityblock")
    return float(D[-1, -1] / len(wp))

KEYS = ["rate", "pause_per_s", "pause_mean", "f0_mean", "f0_std", "f0_range"]

def summarize(pairs):
    """pairs: list of (real_analysis, gen_analysis). Returns mean real, mean gen, mean |diff| per key, mean DTW."""
    out = {}
    for k in KEYS:
        r = np.array([p[0][k] for p in pairs]); g = np.array([p[1][k] for p in pairs])
        out[f"real_{k}"] = float(np.nanmean(r)); out[f"gen_{k}"] = float(np.nanmean(g))
        out[f"absdiff_{k}"] = float(np.nanmean(np.abs(g - r)))
    out["f0_dtw"] = float(np.nanmean([dtw(p[0]["contour"], p[1]["contour"]) for p in pairs]))
    return out
