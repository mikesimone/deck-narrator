#!/usr/bin/env python3
"""Check a rendered video against its manifest and an expected shape.

  check_video.py OUT.mp4 TEMPDIR EXPECT_JSON

TEMPDIR is the --keep-temp directory (manifest.json, slides.ffconcat, PNGs).
EXPECT_JSON: {"slides": [1, 3, ...], "states": [1, 1, ...],
              "voices": {"3": ["af_heart", "am_michael", ...]}}   (voices optional)

Checks, printing PASS/FAIL for each:
  1. streams: H.264 1920x1080 yuv420p video and AAC audio, both present
  2. the slides and build-state counts are the expected ones
  3. per-slide duration matches an independent formula (pad + narration + gaps
     + holds + pad, or holds + empty duration), within one frame per segment
  4. container, video and audio durations all equal the sum of the slides
  5. a frame grabbed mid-way through every segment matches that segment's PNG
     (so every build state is on screen when it should be, in order)
  6. the voices, part by part, are the expected ones (voice switching and carry-over)
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import narrate  # noqa: E402  (constants only: TURN_GAP, CHUNK_GAP, FPS)

PAD, EMPTY, HOLD = 0.75, 3.0, narrate.BUILD_HOLD
mp4, tmp, expect = sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3])
manifest = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{': ' + detail if detail else ''}")


probe = json.loads(subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", mp4]))
streams = {s["codec_type"]: s for s in probe["streams"]}
v, a = streams.get("video"), streams.get("audio")
check("streams", v and a and v["codec_name"] == "h264" and a["codec_name"] == "aac"
      and v["pix_fmt"] == "yuv420p" and (v["width"], v["height"]) == (1920, 1080),
      f"{v and v['codec_name']} {v and v['width']}x{v and v['height']} {v and v['pix_fmt']}, {a and a['codec_name']}")

check("slides", [m["slide"] for m in manifest] == expect["slides"], str([m["slide"] for m in manifest]))
check("build states", [m["build_states"] for m in manifest] == expect["states"], str([m["build_states"] for m in manifest]))

# 3. independent duration formula
frame = 1 / narrate.FPS
total_expected, n_segments = 0.0, 0
for m in manifest:
    parts, n = m["parts"], m["build_states"]
    if parts:
        exp = PAD + sum(p["seconds"] for p in parts) + PAD
        said = {p["step"] for p in parts}
        exp += narrate.TURN_GAP * len([k for k in said if k > 0])        # the beat after each click
        exp += HOLD * len([k for k in range(1, n) if k not in said])     # builds nobody talks over
        for prev, cur in zip(parts, parts[1:]):
            if prev["step"] == cur["step"]:
                exp += narrate.TURN_GAP if prev["voice"] != cur["voice"] else narrate.CHUNK_GAP
    else:
        exp = HOLD * (n - 1) + EMPTY
    segs = len(m["segments"])
    n_segments += segs
    total_expected += exp
    check(f"slide {m['slide']} duration", abs(m["slide_seconds"] - exp) <= segs * frame + 1e-6,
          f"expected {exp:.3f}s, got {m['slide_seconds']:.3f}s over {segs} segment(s)")

# 4. container / stream durations
fmt, vd, ad = float(probe["format"]["duration"]), float(v["duration"]), float(a["duration"])
tol = n_segments * frame + 0.05
check("total duration", all(abs(d - total_expected) <= tol for d in (fmt, vd, ad)),
      f"expected {total_expected:.3f}s; container {fmt:.3f}, video {vd:.3f}, audio {ad:.3f} (tolerance {tol:.3f})")

# 5. the right picture during every segment: of all the build-state PNGs of a
# slide, the one that segment should show must be the best match for a frame
# grabbed mid-segment. (Absolute PSNR is a poor test here: the RGB to yuv420p
# conversion alone costs ~10 dB. Ranking against the slide's other states is
# what proves the right build is on screen.) Visually identical states, e.g. an
# emphasis-only click, tie, and a tie is fine.
pngs = [line.split("'")[1] for line in (tmp / "slides.ffconcat").read_text(encoding="utf-8").splitlines() if line.startswith("file ")][:-1]


def psnr(mp4_time, png):
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-ss", f"{mp4_time:.3f}", "-i", mp4, "-i", png, "-frames:v", "1", "-filter_complex",
         "[0]scale=640:360[x];[1]scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2[y];"
         "[x][y]psnr", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(out.split("average:")[1].split()[0].replace("inf", "99"))


segs = [(m, s, png) for (m, s), png in zip([(m, s) for m in manifest for s in m["segments"]], pngs)]
t, bad, margins = 0.0, [], []
for m, seg, png in segs:
    mid = t + seg["seconds"] / 2
    t += seg["seconds"]
    candidates = sorted({p for mm, _, p in segs if mm["slide"] == m["slide"]})
    if len(candidates) == 1:
        continue                                  # one picture for the whole slide: nothing to rank
    scores = {p: psnr(mid, p) for p in candidates}
    own, best = scores[png], max(scores.values())
    rivals = [v for p, v in scores.items() if v < own - 0.5]
    margins.append(own - max(rivals) if rivals else 99)
    if own < best - 0.5:
        bad.append(f"slide {m['slide']} state {seg['state']}")
check("frames match states", not bad,
      ("wrong picture: " + ", ".join(bad)) if bad else
      f"{len(segs)} segments; each build state is the best match "
      f"(smallest lead over a different state: {min(margins, default=99):.1f} dB)")

# 6. voices
for slide, want in expect.get("voices", {}).items():
    got = [p["voice"] for m in manifest if m["slide"] == int(slide) for p in m["parts"]]
    check(f"slide {slide} voices", got == want, " > ".join(got))

print("VERIFY: PASS" if ok else "VERIFY: FAIL")
sys.exit(0 if ok else 1)
