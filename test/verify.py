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

print("ALL: FAIL" if failed else "ALL: PASS")
sys.exit(1 if failed else 0)
