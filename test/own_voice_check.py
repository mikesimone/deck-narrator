#!/usr/bin/env python3
"""End-to-end check of "your own voice" with the real Chatterbox: set it up, make a voice
from a recording, speak with it, narrate a slide with it, a voice pack with a timbre
recording, the update of a 1.3.0 setup, removing it all. Downloads 4 to 6 GB.
CI runs it on Linux (from source) and Windows (the built .exe), on the CPU.

  python test/own_voice_check.py [--exe path/to/deck-narrator] [--skip-install]

Checks the words with faster-whisper when it's installed.
"""
import argparse
import json
import os
import zipfile
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


def annotate(title, text):
    """On GitHub Actions, put the failure in an annotation, readable without the full log."""
    if os.environ.get("GITHUB_ACTIONS"):
        msg = text[-4000:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::error title={title}::{msg}", flush=True)


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
            annotate(f"own voice: {a[0]}", r.stderr + r.stdout)
            sys.exit(f"FAILED: {' '.join(str(x) for x in a)}")
        return r

    if not args.skip_install:
        run("--install-own-voice", timeout=5400)
    home = Path(os.environ.get("DECK_NARRATOR_OWN_VOICE_HOME") or
                (Path(os.environ["LOCALAPPDATA"]) if os.name == "nt" else Path.home() / ".local" / "share")
                / "deck-narrator" / "chatterbox")
    ready = json.loads((home / "ready.json").read_text(encoding="utf-8"))
    print(f"ready.json: {ready}")
    assert ready.get("checker") and "cuda" in ready, "the setup didn't record the checker and the GPU"

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
    first = run("--voice", "ci-voice", "--sample", "One more line, to check the logs.", "-o", work / "log.wav")
    assert "cut-off check isn't installed" not in first.stderr, "the cut-off check didn't load"
    assert "running on the processor" in first.stderr, first.stderr[-2000:]

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

    deck = ROOT / "test" / "test-deck.pptx"
    if not deck.is_file():
        subprocess.run([sys.executable, str(ROOT / "test" / "make_test_deck.py")], check=True, stdout=subprocess.DEVNULL)
    video = work / "own.mp4"
    run(deck, "--voice", "ci-voice", "--slides", "1", "-o", video, timeout=1800)
    assert video.is_file() and video.stat().st_size > 10_000, "no video"

    # A voice pack whose timbre_reference sets the sound and reference.wav the delivery.
    timbre = work / "timbre.wav"
    run("--voice", "af_heart", "--sample", REFERENCE, "-o", timbre)
    pack = work / "pack.zip"
    with zipfile.ZipFile(pack, "w") as z:
        z.write(ref, "reference.wav")
        z.write(timbre, "timbre_reference.wav")
        z.writestr("voice.json", json.dumps({"timbre_reference": "timbre_reference.wav", "cfg_weight": 0.3,
                                            "pause_scale": 1.6, "speed": 0.95}))
    run("--add-voice", "ci-pack", pack)
    run("--voice", "ci-pack", "--sample", SAY, "-o", work / "pack.wav", timeout=1800)
    assert sf.info(str(work / "pack.wav")).duration > 1.5, "the voice pack said nothing"

    # A setup from 1.3.0 (no checker in ready.json) is brought up to date on first use.
    old = {k: v for k, v in ready.items() if k not in ("checker", "cuda", "mps", "gpu")}
    (home / "ready.json").write_text(json.dumps(old), encoding="utf-8")
    up = run("--voice", "ci-voice", "--sample", "Updated, and still talking.", "-o", work / "up.wav", timeout=1800)
    assert "Updating your own voice's setup" in up.stderr, "a 1.3.0 setup wasn't updated"
    assert json.loads((home / "ready.json").read_text(encoding="utf-8")).get("checker"), "ready.json not updated"

    run("--remove-voice", "ci-voice")
    run("--remove-voice", "ci-pack")
    assert "ci-voice" not in run("--list-voices").stdout
    run("--remove-own-voice-support")
    assert not home.exists(), "Chatterbox wasn't removed"
    print("own voice: OK")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, subprocess.TimeoutExpired) as e:
        annotate("own voice check", f"{type(e).__name__}: {e}")
        raise
