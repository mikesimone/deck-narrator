#!/usr/bin/env python3
"""Used by .github/workflows/pronounce-ab.yml: says each line of $TEXTS ("|"-separated) in two
voices, and reports each clip's length, its longest pause inside the speech, and what
Whisper hears. A pronunciation that leaves a long pause mid-word, or that Whisper hears as
something else, is the wrong one."""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

out = Path(sys.argv[1])
texts = [t.strip() for t in os.environ["TEXTS"].split("|") if t.strip()]
here = Path(__file__).resolve().parent.parent
from faster_whisper import WhisperModel  # noqa: E402
whisper = WhisperModel("base.en", device="cpu", compute_type="int8")


def longest_pause(wav, sr):
    frame = int(sr * 0.01)
    rms = np.array([np.sqrt(np.mean(wav[i:i + frame] ** 2)) for i in range(0, len(wav) - frame, frame)])
    loud = rms > rms.max() * 0.05
    idx = np.flatnonzero(loud)
    if len(idx) == 0:
        return 0.0
    gaps = np.diff(idx) - 1
    return float(gaps.max() * 0.01) if len(gaps) else 0.0


lines = []
for v in ("af_heart", "am_michael"):
    for i, t in enumerate(texts, 1):
        f = out / f"{i}-{v}.wav"
        subprocess.run([str(here / ".venv/bin/python"), str(here / "narrate.py"), "--voice", v, "--sample", t,
                        "-o", str(f)], check=True, capture_output=True)
        wav, sr = sf.read(f)
        heard = " ".join(s.text.strip() for s in whisper.transcribe(str(f), language="en")[0])
        lines.append(f"{i}-{v}: {len(wav) / sr:.2f}s, longest pause {longest_pause(wav, sr):.2f}s | {t} | heard: {heard}")
(out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
