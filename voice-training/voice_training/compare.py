"""Step `compare`: should the "lines" sessions (isolated sentences) train T3 too? T3 learns rhythm, and sentences
read one at a time are often faster/flatter than connected speech. On dataset short clips (3-15 s, comparable
length): syllables/s, pauses (>= 150 ms) per second and F0 5-95 % range, duration-weighted, lines vs items
sessions. Within 10 % on all three -> T3 trains on both (and the train step also trains an items-only T3 to compare).
-> ft/prosody_sessions.json"""
import csv, collections, numpy as np
from . import prosody
from .common import CSV

def run(w):
    D = w.p("dataset"); split = {f: (sp, k) for f, sp, k in csv.reader(open(D / "split.csv"), **CSV)}
    per = collections.defaultdict(list)
    for f, t in csv.reader(open(D / "metadata.csv", encoding="utf-8"), **CSV):
        if split[f][1] != "s": continue
        a = prosody.analyze(str(D / "wavs" / f), t); per[w.session_kind(int(f[1:].split("_")[0]))].append((a["dur"], a["rate"], a["pause_per_s"], a["f0_range"]))
    def agg(rows):
        r = np.array(rows); wt = r[:, 0]
        return dict(n=len(r), min=round(wt.sum() / 60, 1), **{k: round(float(np.average(r[:, j], weights=wt)), 3) for j, k in ((1, "rate"), (2, "pause_per_s"), (3, "f0_range"))})
    out = {k: agg(v) for k, v in per.items()}
    if "lines" in out and "items" in out:
        out["rel_diff"] = {k: round(out["lines"][k] / out["items"][k] - 1, 3) for k in ("rate", "pause_per_s", "f0_range")}
        out["lines_in_t3"] = all(abs(v) <= 0.10 for v in out["rel_diff"].values())
    w.save_json("ft/prosody_sessions.json", out)
    for k, v in out.items(): print(k, v)
