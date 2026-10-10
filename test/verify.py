#!/usr/bin/env python3
"""The whole test suite, on Linux or Windows: unit tests, then two end-to-end
renders checked with ffprobe and frame comparison (check_video.py).

  test-deck.pptx  narration basics: stage directions, hidden slide, empty slide, long notes
  anim-deck.pptx  animation builds and voice switching

Run with the venv's Python:  .venv/bin/python test/verify.py   (Windows: .venv\\Scripts\\python test\\verify.py)
Extra arguments go to deck-narrator, e.g. --device cpu. To test a packaged build
instead of the source, put --exe PATH first:  verify.py --exe dist/deck-narrator/deck-narrator.exe
"""
import json
import os
import tempfile
import shutil
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
root = here.parent
py = sys.executable
extra = sys.argv[1:]
tool = [py, str(root / "narrate.py")]
if extra[:1] == ["--exe"]:
    tool, extra = [str(Path(extra[1]).resolve())], extra[2:]


def step(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


step([py, "-m", "unittest", "discover", "-s", str(here)])          # fast, no GPU
failed = False


def render(deck, expect, *args):
    global failed
    print(f"== {deck.name}", flush=True)
    r = subprocess.run([*tool, str(deck), "--keep-temp", *args, *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in r.stderr.splitlines():
        if line.startswith(("Deck", "Done", "  note", "deck-narrator: error")):
            print(line)
    kept = [l.split("Kept intermediate files in ", 1)[1] for l in r.stderr.splitlines() if "Kept intermediate" in l]
    if r.returncode != 0 or not kept:
        print(r.stderr)
        failed = True
        return
    c = subprocess.run([py, str(here / "check_video.py"), str(deck.with_suffix(".mp4")), kept[0], json.dumps(expect)])
    failed |= c.returncode != 0
    shutil.rmtree(kept[0], ignore_errors=True)


step([py, str(here / "make_test_deck.py")], stdout=subprocess.DEVNULL)
render(here / "test-deck.pptx", {"slides": [1, 3, 4, 5], "states": [1, 1, 1, 1]},
       "--pronunciations", str(here / "pronunciations.txt"))

step([py, str(here / "make_anim_deck.py")], stdout=subprocess.DEVNULL)
render(here / "anim-deck.pptx", {
    "slides": [1, 2, 3, 4, 5], "states": [4, 4, 1, 1, 3],
    "voices": {"1": ["af_heart"] * 4,
               "3": ["af_heart", "am_michael", "bf_emma", "af_heart", "am_michael"],
               "4": ["am_michael"]}})



def cli(*args, env=None):
    return subprocess.run([*tool, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=dict(os.environ, **(env or {})))


# Check pronunciation, fix a word, and the sample cache, through the same program.
print("== pronunciation check, fix and sample cache", flush=True)
r = cli(str(here / "test-deck.pptx"), "--check-pronunciation", "--json")
try:
    issues = json.loads(next(l for l in r.stdout.splitlines() if l.startswith("{"))) ["issues"]
    print(f"check: {len(issues)} word(s): {', '.join(sorted({i['word'] for i in issues}))}")
except (StopIteration, ValueError, KeyError):
    print(r.stdout, r.stderr)
    failed = True
    issues = []
if issues:
    i = issues[0]
    tmpdir = Path(tempfile.mkdtemp())
    deck = tmpdir / "fix.pptx"
    shutil.copy(here / "test-deck.pptx", deck)
    f = cli(str(deck), "--fix-word", str(i["slide"]), i["word"], str(i["n"]), i["options"][-1]["phonemes"])
    after = cli(str(deck), "--check-pronunciation", "--json")
    left = json.loads(next(l for l in after.stdout.splitlines() if l.startswith("{")))["issues"] if after.returncode == 0 else None
    ok = f.returncode == 0 and left is not None and len(left) == len(issues) - 1 \
        and (tmpdir / "fix (before deck-narrator).pptx").is_file()
    print(f"fix-word: {'ok' if ok else 'FAILED'}")
    if not ok:
        print(f.stdout, f.stderr, after.stderr)
    failed |= not ok
cache = {"DECK_NARRATOR_SAMPLE_CACHE": tempfile.mkdtemp()}
wav = Path(tempfile.mkdtemp()) / "s.wav"
first = cli("--sample", "Cache me if you can.", "-o", str(wav), *extra, env=cache)
second = cli("--sample", "Cache me if you can.", "-o", str(wav), *extra, env=cache)
ok = first.returncode == 0 and second.returncode == 0 and "saved copy" in second.stderr and wav.stat().st_size > 1000
print(f"sample cache: {'ok' if ok else 'FAILED'}")
if not ok:
    print(first.stderr, second.stderr)
failed |= not ok

print("ALL: FAIL" if failed else "ALL: PASS")
sys.exit(1 if failed else 0)
