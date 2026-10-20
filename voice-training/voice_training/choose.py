"""Steps `refs`, `pick-t3`, `pick-s3gen`, `sweep`: choose references, checkpoints and generation settings.
Every choice is scored on held-out clips from the "items" sessions (talk paragraphs / unscripted), generated with
generate_clean exactly as the pack will be used, against the real held-out recordings."""
import collections, itertools, json, os, glob
import numpy as np, soundfile as sf, librosa, torch
from . import prosody

def _val(w, n=None):
    items = torch.load(w.p("ft", "t3_tokens.pt"))
    val = sorted((i for i in items if i["split"] == "val" and w.session_kind(int(i["rec"][1:])) == "items"), key=lambda i: i["file"])
    if n and n < len(val): val = [val[round(k * (len(val) - 1) / (n - 1))] for k in range(n)]
    return [(f"val_{i['file'][:-4]}", i["text"]) for i in val]

def refs(w):
    """4 train clips, 10-15 s, items sessions, one per kit item: closest to the median speaking rate with
    below-median F0 range and loudness variation (calm, typical delivery) -> ft/refs.json."""
    def lvar(p):
        y = librosa.load(p, sr=16000)[0]; r = librosa.feature.rms(y=y)[0]; r = r[r > r.max() * 0.05]; return float(np.std(20 * np.log10(r)))
    cands = []
    for i in torch.load(w.p("ft", "t3_tokens.pt")):
        p = str(w.p("dataset", "wavs", i["file"]))
        if i["split"] != "train" or w.session_kind(int(i["rec"][1:])) != "items" or not 10 <= sf.info(p).duration <= 15: continue
        a = prosody.analyze(p, i["text"]); a["lvar"] = lvar(p); cands.append((p, a))
    if not cands: raise SystemExit("no 10-15 s train clips in items sessions")
    M = {k: np.median([c[1][k] for c in cands]) for k in ("rate", "f0_range", "lvar")}; S = {k: np.std([c[1][k] for c in cands]) + 1e-9 for k in M}
    cands.sort(key=lambda c: abs(c[1]["rate"] - M["rate"]) / S["rate"] + c[1]["f0_range"] / S["f0_range"] + c[1]["lvar"] / S["lvar"])
    picks, seen = [], set()
    for p, a in cands:
        it = os.path.basename(p).rsplit("_", 1)[0]
        if it not in seen: seen.add(it); picks.append(p)
        if len(picks) == 4: break
    w.save_json("ft/refs.json", picks); print("references:", [os.path.basename(p) for p in picks])

def _table(w, name, rows, jobs, ref):
    from .evalkit import Gen, Scorer
    path = w.p("ft", f"{name}.json"); res = json.loads(path.read_text()) if path.exists() else {}
    todo = [k for k in rows if k not in res]
    if todo:
        g = Gen()
        for k in todo: g.load(**rows[k]); g.run(jobs, str(w.p("out", name, k)), ref); print("generated", k, flush=True)
        del g; torch.cuda.empty_cache(); s = Scorer(w)
        for k in todo:
            res[k] = dict(rows[k], **s.score(str(w.p("out", name, k)), jobs)); path.write_text(json.dumps(res, indent=1))
            r = res[k]; print(f"{k:24s} sim {r['spk_sim']:.3f} wer {r['wer']:.3f} rate {r['gen_rate']:.2f}/{r['real_rate']:.2f} hf {r['hf_ratio']:.4f}/{r['hf_real']:.4f}", flush=True)
    return res

NOVEL = ["Click next, and the narrator reads the slide.", "Our quarterly revenue grew by 14 percent, driven mostly by enterprise renewals.",
         "The migration to Kubernetes finished two weeks ahead of schedule.", "Let's look at the architecture diagram.",
         "Each region keeps its own replica of the database.", "Latency dropped from 230 milliseconds to just under 90.",
         "If you remember one thing from today, make it this: patch your firewall.", "Here is the roadmap for the next three quarters.",
         "The pilot ran in Denver, Toronto, and Amsterdam.", "We compared three vendors on cost, support, and integration.",
         "Questions are welcome at the end of the presentation.", "The new dashboard updates every thirty seconds.",
         "Multi-factor authentication stopped almost every credential attack.", "Version 3.2 adds offline mode and a dark theme.",
         "Thanks to everyone on the platform team for making this happen.", "The budget request is summarized in the appendix.",
         "Our customers asked for faster onboarding, so we rebuilt the wizard.", "This chart shows adoption by month since January.",
         "Next, we'll walk through the incident timeline.", "Encryption keys rotate automatically every ninety days.",
         "That brings us to the final recommendation.", "The survey had over four thousand responses.", "Let's open it up for discussion."]

def _novel(w, rows, ref):
    """Robustness on text the speaker never read: WER and the share of sentences whose LAST word survives (fine-tuned
    T3 tends to swallow sentence-final / rarer words once it starts overfitting), 2 seeds each."""
    import re, jiwer
    from .evalkit import Gen
    path = w.p("ft", "pick_t3_novel.json"); res = json.loads(path.read_text()) if path.exists() else {}
    todo = [k for k in rows if k not in res]
    if not todo: return res
    jobs = [(f"n{k:02d}_{s}", t) for k, t in enumerate(NOVEL) for s in (0, 1)]; g = Gen()
    for k in todo: g.load(**rows[k]); g.run(jobs, str(w.p("out", "pick_t3_novel", k)), ref)
    del g; torch.cuda.empty_cache()
    from faster_whisper import WhisperModel
    wm = WhisperModel(w.cfg["whisper_model"], device="cuda", compute_type="float16")
    n = lambda s: " ".join(re.sub(r"[^a-z0-9' ]", " ", s.lower().replace("-", " ")).split())
    for k in todo:
        refs, hyps = [], []
        for fn, t in jobs:
            p = str(w.p("out", "pick_t3_novel", k, f"{fn}.wav")); refs.append(n(t))
            hyps.append(n(" ".join(x.text for x in wm.transcribe(librosa.load(p, sr=16000)[0], language="en", beam_size=5)[0])))
        res[k] = dict(novel_wer=jiwer.wer(refs, hyps), last_word_ok=float(np.mean([bool(h) and h.split()[-1] == r.split()[-1] for r, h in zip(refs, hyps)])))
        path.write_text(json.dumps(res, indent=1)); print(f"{k:24s} novel WER {res[k]['novel_wer']:.3f} last word {res[k]['last_word_ok']:.2f}", flush=True)
    return res

def pick_t3(w):
    """Every train-t3 run, every epoch (+ stock), stock S3Gen, the top reference. Gate 1, novel text: last word right
    in >= 98 % of sentences and WER <= 4 %. Gate 2, held-out paragraphs: WER <= 4 %. Then best speaker similarity
    (ties: closest pace). Falls back to stock T3 if nothing passes."""
    ref = w.load_json("ft/refs.json")[0]; rows = {"stock": dict(t3=None)}
    for d in sorted(glob.glob(str(w.p("ft", "t3_*")))):
        for p in sorted(glob.glob(f"{d}/t3_e*.pt")): rows[f"{os.path.basename(d)}_{os.path.basename(p)[3:-3]}"] = dict(t3=p)
    nov = _novel(w, rows, ref)
    keep = {k: v for k, v in rows.items() if k == "stock" or (nov[k]["last_word_ok"] >= 0.98 and nov[k]["novel_wer"] <= 0.04)}
    res = _table(w, "pick_t3", keep, _val(w), ref)
    ok = [k for k in res if k != "stock" and res[k]["wer"] <= 0.04] or ["stock"]
    best = max(ok, key=lambda k: (round(res[k]["spk_sim"], 3), -abs(res[k]["gen_rate"] - res[k]["real_rate"])))
    w.save_json("ft/pick.json", dict(t3=res[best]["t3"])); print("T3 ->", best)

def pick_s3gen(w):
    """Flow epochs 5/10/15/20 with the stock vocoder -> best speaker sim; then the vocoder checkpoints with that flow
    -> the brightest one that keeps speaker sim within 0.01 of the stock vocoder."""
    pk = w.load_json("ft/pick.json"); ref = w.load_json("ft/refs.json")[0]; jobs = _val(w)
    rows = {f"flow_e{e}": dict(t3=pk["t3"], flow=str(w.p("ft", "s3gen", f"flow_e{e}.pt"))) for e in (5, 10, 15, 20) if w.p("ft", "s3gen", f"flow_e{e}.pt").exists()}
    rows["stock"] = dict(t3=pk["t3"])
    res = _table(w, "pick_flow", rows, jobs, ref)
    fb = max((k for k in res if k != "stock" and res[k]["wer"] <= 0.04), key=lambda k: res[k]["spk_sim"]); flow = res[fb]["flow"]
    rows = {"stock_vocoder": dict(t3=pk["t3"], flow=flow)}
    for p in sorted(glob.glob(str(w.p("ft", "hift", "hift_s*.pt")))): rows[os.path.basename(p)[:-3]] = dict(t3=pk["t3"], flow=flow, hift=p)
    res = _table(w, "pick_hift", rows, jobs, ref); base = res["stock_vocoder"]["spk_sim"]
    ok = [k for k in res if res[k]["spk_sim"] >= base - 0.01 and res[k]["wer"] <= 0.04] or ["stock_vocoder"]
    hb = max(ok, key=lambda k: res[k]["hf_ratio"])
    w.save_json("ft/pick.json", dict(pk, flow=flow, hift=res[hb].get("hift"))); print("flow ->", fb, "| vocoder ->", hb)

RANK = {"pace": lambda r: abs(r["gen_rate"] - r["real_rate"]) / r["real_rate"], "sim": lambda r: -r["spk_sim"],
        "bright": lambda r: abs(r["hf_ratio"] - r["hf_real"]) / r["hf_real"],
        "f0range": lambda r: abs(r["gen_f0_range"] - r["real_f0_range"]) / r["real_f0_range"],
        "pauses": lambda r: abs(r["gen_pause_per_s"] - r["real_pause_per_s"]), "dtw": lambda r: r["f0_dtw"]}

def rank(res):
    keys = [k for k, r in res.items() if r["wer"] <= 0.04] or list(res); ranks = collections.defaultdict(float)
    for f in RANK.values():
        for pos, k in enumerate(sorted(keys, key=lambda k: f(res[k]))): ranks[k] += pos
    return sorted(keys, key=lambda k: ranks[k])

def sweep(w):
    """Stage 1: references (each of 4 alone; split T3 <- top 2 / S3Gen <- other 2) x exaggeration {.3,.5} x cfg {.3,.5}.
    Stage 2: the best setup x cfg {.2,.3,.4} x exaggeration {.2,.3,.4} x temperature {.7,.8}. 12 held-out clips;
    WER <= 4 % only; rank-sum over pace, speaker sim, brightness, F0 range, pauses, F0 DTW -> ft/settings.json."""
    from .evalkit import Gen, Scorer
    pk = w.load_json("ft/pick.json"); R = w.load_json("ft/refs.json"); jobs = _val(w, 12)
    b = lambda p: os.path.basename(p)[:-4]
    setups = {f"single:{b(r)}": (r, None) for r in R}; setups.update({f"split:{b(t)}>{b(g)}": (g, t) for t in R[:2] for g in R[2:]})
    path = w.p("ft", "sweep.json"); res = json.loads(path.read_text()) if path.exists() else {}
    g = Gen(); g.load(pk["t3"], pk.get("flow"), pk.get("hift")); s = Scorer(w)
    def do(name, ex, cfg, temp):
        key = f"{name}|ex{ex}|cfg{cfg}|t{temp}"
        if key in res: return
        gen_ref, t3_ref = setups[name]; od = str(w.p("out", "sweep", key.replace("|", "__").replace(":", "_").replace(">", "_to_")))
        g.run(jobs, od, gen_ref, exaggeration=ex, cfg_weight=cfg, temperature=temp, t3_ref=t3_ref)
        res[key] = dict(setup=name, gen_ref=gen_ref, t3_ref=t3_ref, exaggeration=ex, cfg_weight=cfg, temperature=temp, **s.score(od, jobs))
        path.write_text(json.dumps(res, indent=1)); r = res[key]
        print(f"{key:56s} sim {r['spk_sim']:.3f} wer {r['wer']:.3f} rate {r['gen_rate']:.2f}/{r['real_rate']:.2f} hf {r['hf_ratio']:.4f}/{r['hf_real']:.4f}", flush=True)
    for name, ex, cfg in itertools.product(setups, (0.3, 0.5), (0.3, 0.5)): do(name, ex, cfg, 0.8)
    best_setup = res[rank({k: v for k, v in res.items() if v["temperature"] == 0.8 and "cfg0.2" not in k})[0]]["setup"]
    for cfg, ex, temp in itertools.product((0.2, 0.3, 0.4), (0.2, 0.3, 0.4), (0.7, 0.8)): do(best_setup, ex, cfg, temp)
    best = res[rank(res)[0]]
    # post-generation pace controls, only if the winner is still clearly off the speaker's measured pace
    speed = round(min(1.0, max(0.85, best["real_rate"] / best["gen_rate"])), 2) if best["gen_rate"] > best["real_rate"] * 1.03 else None
    pause = round(min(1.8, best["real_pause_per_s"] / max(best["gen_pause_per_s"], 1e-3)), 2) if best["gen_pause_per_s"] < best["real_pause_per_s"] * 0.8 else None
    out = dict(best, speed=speed, pause_scale=pause); w.save_json("ft/settings.json", out)
    print("settings ->", {k: out[k] for k in ("setup", "exaggeration", "cfg_weight", "temperature", "speed", "pause_scale", "spk_sim", "wer", "gen_rate", "real_rate")})
