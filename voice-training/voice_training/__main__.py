"""python -m voice_training <step> --work <folder>

First: python -m voice_training kit --work <folder> --arctic cmuarctic.data --paragraphs mine.txt [...]
(see voice_training/kit.py), record, put the WAVs in <folder>/raw/. Then the steps, in order (`all` runs qc .. verify):
  qc          check raw/*.wav, detect sessions, 70 Hz high-pass -> audio/
  transcribe  Whisper large-v3 with word timestamps -> transcripts/
  dataset     kit-aligned 3-15 s + 10-25 s clips, ~5 % validation -> dataset/
  compare     prosody of "lines" vs "items" sessions: may sentences train T3 too?
  features    T3 tokens + S3Gen mels/x-vectors -> ft/
  refs        pick 4 calm, typical reference clips
  train-t3    fine-tune T3 (items sessions; plus items+lines if `compare` allows)
  pick-t3     choose the T3 run/epoch on held-out paragraphs
  train-s3gen fine-tune S3Gen's flow on all sessions
  train-hift  fine-tune S3Gen's vocoder on all sessions
  pick-s3gen  choose the flow epoch and vocoder step
  sweep       reference setups x settings -> ft/settings.json
  pack        -> out/voice.zip
  verify      fresh-process strict load + test line
Every step is resumable / skips finished work where it can; the trainers always retrain.
"""
import argparse, os, subprocess, sys
from .common import Work, setup_platform

ORDER = ["qc", "transcribe", "dataset", "compare", "features", "refs", "train-t3", "pick-t3", "train-s3gen", "train-hift",
         "pick-s3gen", "sweep", "pack", "verify"]

def sub(module, *args):
    """Trainers and the verifier run in a fresh Python process (frees the GPU; verify must not reuse loaded weights)."""
    r = subprocess.run([sys.executable, "-m", f"voice_training.{module}", *map(str, args)], cwd=os.path.dirname(os.path.dirname(__file__)))
    if r.returncode: sys.exit(f"{module} failed ({r.returncode})")

def step(w, name):
    print(f"=== {name}", flush=True)
    if name == "qc": from . import qc; qc.run(w)
    elif name == "transcribe": from . import transcribe; transcribe.run(w)
    elif name == "dataset": from . import dataset; dataset.run(w)
    elif name == "compare": from . import compare; compare.run(w)
    elif name == "features": from . import features; features.run(w)
    elif name == "refs": from . import choose; choose.refs(w)
    elif name == "train-t3":
        import torch
        recs = sorted({i["rec"] for i in torch.load(w.p("ft", "t3_tokens.pt"))}, key=lambda r: int(r[1:]))
        items = [r for r in recs if w.session_kind(int(r[1:])) == "items"]; lines = [r for r in recs if r not in items]
        use = w.cfg["t3_lines_sessions"]  # "auto": also train an items+lines run when `compare` allows; pick-t3 decides
        if use == "auto": use = w.p("ft", "prosody_sessions.json").exists() and w.load_json("ft/prosody_sessions.json").get("lines_in_t3", False)
        runs = {"t3_items": items} | ({"t3_all": recs} if use and lines else {})
        for name_, rs in runs.items():
            sub("train_t3", "--tokens", w.p("ft", "t3_tokens.pt"), "--out", w.p("ft", name_), "--recs", ",".join(rs), "--val-recs", ",".join(items))
    elif name == "pick-t3": from . import choose; choose.pick_t3(w)
    elif name == "train-s3gen": sub("train_s3gen", "--data", w.p("ft", "s3gen_feats.pt"), "--out", w.p("ft", "s3gen"))
    elif name == "train-hift": sub("train_hift", "--data", w.p("ft", "s3gen_feats.pt"), "--wavs", w.p("dataset", "wavs"), "--out", w.p("ft", "hift"))
    elif name == "pick-s3gen": from . import choose; choose.pick_s3gen(w)
    elif name == "sweep": from . import choose; choose.sweep(w)
    elif name == "pack": from . import pack; pack.run(w)
    elif name == "verify": sub("verify_cli", w.p("out", "voice.zip"))

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "kit":
        from . import kit
        ka = argparse.ArgumentParser(); ka.add_argument("--work", required=True); k, rest = ka.parse_known_args(sys.argv[2:])
        return kit.main(Work(k.work), rest)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=ORDER + ["all"]); ap.add_argument("--work", required=True)
    ap.add_argument("--from", dest="start", choices=ORDER, help="with `all`: start at this step")
    a = ap.parse_args(); setup_platform(); w = Work(a.work)
    for s in (ORDER[ORDER.index(a.start or "qc"):] if a.step == "all" else [a.step]): step(w, s)

if __name__ == "__main__":
    main()
