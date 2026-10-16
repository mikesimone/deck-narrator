#!/usr/bin/env python3
"""End-to-end check of "your own voice" with the real Chatterbox: set it up, make a voice
from a recording, speak with it, narrate a slide with it, remove it. Downloads 4 to 6 GB.
CI runs it on Linux (from source) and Windows (the built .exe), on the CPU.

  python test/own_voice_check.py [--exe path/to/deck-narrator] [--skip-install]

Checks the words with faster-whisper when it's installed.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = ("Good morning, everyone. Thanks for joining. Today I'll walk you through how the new "
             "release works, what changed since last quarter, and where we go next. Let's start "
             "with the big picture, and then we'll dig into the details together.")
SAY = "Deck Narrator can speak in your own voice, slide by slide."


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--exe", help="the built deck-narrator; default: narrate.py with this Python")
    p.add_argument("--skip-install", action="store_true")
    args = p.parse_args()
    cli = [args.exe] if args.exe else [sys.executable, str(ROOT / "narrate.py")]
    work = Path(tempfile.mkdtemp(prefix="own-voice-check-"))
    env = dict(os.environ, DECK_NARRATOR_MY_VOICES=str(work / "my-voices"),
               DECK_NARRATOR_SAMPLE_CACHE=str(work / "samples"), PYTHONIOENCODING="utf-8")

    def run(*a, timeout=3600):
        t0 = time.time()
        print(">", " ".join(str(x) for x in a), flush=True)
        r = subprocess.run(cli + [str(x) for x in a], env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        print(r.stderr[-6000:], end="", flush=True)
        print(f"  ({time.time() - t0:.0f}s, exit {r.returncode})", flush=True)
        if r.returncode:
            print(r.stdout)
            sys.exit(f"FAILED: {' '.join(str(x) for x in a)}")
        return r

    if not args.skip_install:
        run("--install-own-voice", timeout=5400)

    ref = work / "reference.wav"
    run("--voice", "am_michael", "--sample", REFERENCE, "-o", ref)
    print(f"reference: {sf.info(str(ref)).duration:.1f}s")
    run("--add-voice", "ci-voice", ref)
    listing = run("--list-voices").stdout
    assert "ci-voice" in listing, listing

    own = work / "own.wav"
    run("--voice", "ci-voice", "--sample", SAY, "-o", own, timeout=1800)
    audio, sr = sf.read(str(own), dtype="float32")
    seconds = len(audio) / sr
    print(f"own voice: {seconds:.2f}s at {sr} Hz, peak {np.abs(audio).max():.2f}")
    assert sr == 24000 and 1.5 < seconds < 12, "the own-voice sample has the wrong length"
    again = run("--voice", "ci-voice", "--sample", SAY, "-o", work / "again.wav")
    assert "saved copy" in again.stderr, "the second identical sample wasn't served from the cache"

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper isn't installed; not checking the words")
    else:
        n = int(len(audio) * 16000 / sr)
        audio16 = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype("float32")
        segs, _ = WhisperModel("base.en", device="cpu", compute_type="int8").transcribe(audio16, language="en")
        heard = " ".join(s.text for s in segs).strip()
        print(f"whisper heard: {heard!r}")
        norm = lambda t: {w.strip(".,!?").lower() for w in t.split()}   # noqa: E731
        overlap = len(norm(SAY) & norm(heard)) / len(norm(SAY))
        assert overlap >= 0.7, f"only {overlap:.0%} of the words came through"

    video = work / "own.mp4"
    run(ROOT / "test" / "test-deck.pptx", "--voice", "ci-voice", "--slides", "1", "-o", video, timeout=1800)
    assert video.is_file() and video.stat().st_size > 10_000, "no video"

    run("--remove-voice", "ci-voice")
    assert "ci-voice" not in run("--list-voices").stdout
    print("own voice: OK")


if __name__ == "__main__":
    main()
