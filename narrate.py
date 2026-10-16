#!/usr/bin/env python3
"""deck-narrator: turn a .pptx with speaker notes into a voice-narrated MP4.

Pipeline: python-pptx notes -> LibreOffice PDF -> pypdfium2 PNGs ->
Kokoro-82M (or, for your own voice, Chatterbox) narration -> ffmpeg (H.264 + AAC, yuv420p, loudness-normalized).
Runs on Linux and Windows.

Speaker notes are a script: [click] advances the slide's animation builds,
[voice: name] switches the narrator. See README.md next to this file.
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import builds as anim

# Kokoro uses a few ops Apple's Metal backend lacks; let torch run those on the CPU
# instead of failing. Must be set before torch is imported.
if sys.platform == "darwin":
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

VERSION = "1.3.0"
SAMPLE_RATE = 24000          # Kokoro's native output rate
FPS = 30
WIDTH, HEIGHT = 1920, 1080
REPO_ID = "hexgrad/Kokoro-82M"
DEFAULT_VOICE = "af_heart"
CHUNK_CHARS = 350            # max characters per TTS call; split at sentence ends
CHUNK_GAP = 0.20             # seconds of silence between TTS chunks of one speaker
TURN_GAP = 0.35              # seconds between a click and the next words, or between two voices
BUILD_HOLD = 1.0             # default seconds per build state that has no narration of its own
LOUDNORM = "I=-16:TP=-1.5:LRA=11"

# Fallback for --list-voices when the HuggingFace listing is unreachable.
KNOWN_VOICES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky", "am_adam",
    "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]
LANG_NAMES = {
    "a": "American English", "b": "British English", "e": "Spanish",
    "f": "French", "h": "Hindi", "i": "Italian", "j": "Japanese",
    "p": "Brazilian Portuguese", "z": "Mandarin Chinese",
}


class Fail(Exception):
    """A user-facing error: printed without a traceback."""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# Phonemes and voice names are printed; a Windows console defaults to a code page
# that can't encode IPA. Never crash on output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------- arguments

def parse_slide_range(spec):
    """'3-5' or '1,3,7-9' -> set of 1-based slide numbers."""
    wanted = set()
    for part in spec.split(","):
        part = part.strip()
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise argparse.ArgumentTypeError(f"bad --slides value: {spec!r} (use e.g. 3-5 or 1,4,6-8)")
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        if lo < 1 or hi < lo:
            raise argparse.ArgumentTypeError(f"bad --slides range: {part!r}")
        wanted.update(range(lo, hi + 1))
    return wanted


def build_parser():
    p = argparse.ArgumentParser(
        prog="deck-narrator",
        description="Turn a PowerPoint deck's speaker notes into a voice-narrated MP4.",
        epilog="In the notes: [click] advances animation builds, [voice: am_michael] switches narrator, "
               "[word](/phonemes/) fixes a pronunciation. Guides: README.md, docs/PRONUNCIATION.md",
    )
    p.add_argument("--version", action="version", version=f"deck-narrator {VERSION}")
    p.add_argument("deck", nargs="?", help="path to the .pptx")
    p.add_argument("-o", "--output", help="output .mp4 path or directory (default: next to the deck, same base name)")
    p.add_argument("--voice", default=DEFAULT_VOICE, help=f"starting voice; [voice: name] in the notes switches it (default: {DEFAULT_VOICE})")
    p.add_argument("--list-voices", action="store_true", help="list available voices and exit")
    p.add_argument("--update-voices", action="store_true", help="download voices that are new or updated on HuggingFace "
                   "(installs with bundled voices only; into a per-user folder) and exit")
    p.add_argument("--speed", type=float, default=1.0, help="speech speed multiplier (default: 1.0)")
    p.add_argument("--pad", type=float, default=0.75, help="seconds of silence before and after each slide's narration (default: 0.75)")
    p.add_argument("--empty-duration", type=float, default=3.0, help="seconds to show a slide with no notes (default: 3.0)")
    p.add_argument("--skip-empty", action="store_true", help="drop slides with no notes instead of showing them silently")
    p.add_argument("--slides", type=parse_slide_range, help="only render these slides, e.g. 3-5 or 1,4,6-8 (PowerPoint numbering)")
    p.add_argument("--no-builds", action="store_true", help="ignore animations: show each slide fully built, as before builds were supported")
    p.add_argument("--build-hold", type=float, default=BUILD_HOLD, help=f"seconds for a build step with no narration of its own (default: {BUILD_HOLD})")
    p.add_argument("--show-builds", action="store_true", help="print each selected slide's build steps and how the notes' [click]s line up, and exit (no video)")
    p.add_argument("--pronunciations", metavar="FILE", help="word=replacement file applied to notes before TTS "
                   "(default: your personal dictionary, if you have one; see --add-word)")
    p.add_argument("--device", choices=["auto", "cuda", "mps", "cpu"], default="auto",
                   help="where Kokoro runs (default: auto = NVIDIA cuda, else Apple Silicon mps, else cpu)")
    p.add_argument("--renderer", choices=["auto", "powerpoint", "keynote", "libreoffice"], default="auto",
                   help="what draws the slides (default: auto = PowerPoint if it's installed, else LibreOffice)")
    p.add_argument("--show-phonemes", action="store_true", help="print each selected slide's script as phonemes, with voices and clicks, and exit (no video)")
    p.add_argument("--phonemes", metavar="TEXT", help="print the phonemes for TEXT and exit, e.g. --phonemes 'a present'")
    p.add_argument("--check-pronunciation", action="store_true",
                   help="list the words in the selected slides' notes that may be said wrong (more than one "
                        "pronunciation, not in the dictionary, or spelled out), with the choices, and exit (no video)")
    p.add_argument("--json", action="store_true", help="with --check-pronunciation: print JSON instead")
    p.add_argument("--fix-word", nargs=4, metavar=("SLIDE", "WORD", "N", "PHONEMES"),
                   help="write [WORD](/PHONEMES/) in place of the N-th WORD in slide SLIDE's notes, saving the deck "
                        "(the original is kept once as '<deck> (before deck-narrator).pptx'), and exit")
    p.add_argument("--add-word", nargs=2, metavar=("WORD", "PHONEMES"),
                   help="save WORD=[WORD](/PHONEMES/) in the dictionary (--pronunciations FILE, else your personal "
                        "dictionary, created if needed), so WORD is said that way in every deck, and exit")
    p.add_argument("--sample", metavar="TEXT", help="speak TEXT with --voice, --speed and --pronunciations into a WAV and exit "
                   "(-o names the .wav; default: deck-narrator-sample.wav in the temp folder)")
    p.add_argument("--keep-temp", action="store_true", help="keep the intermediate files and print where they are")
    p.add_argument("--install-own-voice", action="store_true",
                   help="set up Chatterbox, which speaks in your own voices (downloads 4 to 6 GB, once), and exit")
    p.add_argument("--add-voice", nargs=2, metavar=("NAME", "FILE"),
                   help="make a voice of your own called NAME from FILE: a 10-30 second recording of the person "
                        "(.wav, .flac, .mp3) or a voice pack (.zip), and exit")
    p.add_argument("--remove-voice", metavar="NAME", help="delete your own voice NAME, and exit")
    return p


# ---------------------------------------------------------------- notes

# [pause], [click]... but not [word](/phonemes/), which is Kokoro's inline
# pronunciation override and must reach the TTS intact.
BRACKETED = re.compile(r"\[[^\[\]]*\](?!\()")

# The two stage directions that do something: [click] and [voice: name].
MARKER = re.compile(r"\[\s*(?:(?P<click>click)|voice\s*:\s*(?P<voice>[^\[\]]*?))\s*\](?!\()", re.I)


def clean_notes(text):
    text = BRACKETED.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r" (?=[.,!?;:])", "", text).strip()


# "[present] (/pɹizˈɛnt/)" with a space looks like a stage direction followed by
# junk: [present] would be stripped and Kokoro would read "(/pɹizˈɛnt/)" aloud as
# "slash p r...". Checked on the raw notes, so prose like "(5)" is never flagged.
DETACHED_OVERRIDE = re.compile(r"\[[^\[\]]*\]\s+\((?:/[^)]*/|[+-]?\d(?:\.5)?)\)")


def check_overrides(slides):
    for s in slides:
        m = DETACHED_OVERRIDE.search(s["raw_notes"] or "")
        if m:
            raise Fail(f"slide {s['number']}: pronunciation override {m.group(0)!r} has a space between ] and (. "
                       "Write it as [word](/phonemes/) with nothing in between.")


def check_voice_name(voice, where):
    if is_own_voice(voice):
        return voice
    if not is_kokoro_name(voice) or voice[0] not in LANG_NAMES:
        raise Fail(f"{where}: unknown voice {voice!r}; run --list-voices to see the valid names")
    return voice


def parse_script(raw, voice, default_voice, slide_no, rules=()):
    """Speaker notes -> (parts, clicks, voice at the end).

    A part is {"step": k, "voice": v, "text": t}: what one voice says after k
    clicks. [click] advances k, [voice: name] switches v (and stays switched
    on later slides; [voice: default] goes back to --voice). Every other
    [bracketed] stage direction is dropped, then pronunciations are applied.
    """
    parts, step, pos = [], 0, 0

    def add(segment):
        text = apply_pronunciations(clean_notes(segment), rules)
        if not text:
            return
        if not re.search(r"\w", text):
            # Bare punctuation left after a marker ("done [click]."): it belongs
            # to the words before it, never on its own (Kokoro can't say ".").
            if parts:
                parts[-1]["text"] += text
            return
        if parts and parts[-1]["step"] == step and parts[-1]["voice"] == voice:
            parts[-1]["text"] += " " + text
        else:
            parts.append({"step": step, "voice": voice, "text": text})

    for m in MARKER.finditer(raw or ""):
        add(raw[pos:m.start()])
        pos = m.end()
        if m.group("click"):
            step += 1
        else:
            name = m.group("voice").strip().lower()
            voice = default_voice if name in ("", "default") else check_voice_name(name, f"slide {slide_no}")
    add((raw or "")[pos:])
    return parts, step, voice


DICT_TEMPLATE = """\
# deck-narrator pronunciation dictionary
# One rule per line: word=what to say instead. Whole words, case-sensitive.
# Lines starting with # are comments. Inline fixes in the notes, like
# [present](/pɹizˈɛnt/), beat this file. Full guide: docs/PRONUNCIATION.md
#
# Examples:
# NGINX=engine x
# SQL=sequel
# Kubernetes=koo ber net eez
"""


# Words the voice gets wrong out of the box, fixed for every deck. A rule for the same word
# in your dictionary wins, and so does an inline [word](/phonemes/) in the notes.
# Each was checked with the real voices: rendered both ways and transcribed by a speech
# recognizer (.github/workflows/pronounce-ab.yml).
BUILTIN_PRONUNCIATIONS = [
    ("AI", "[AI](/ˌAˈI/)"),                               # "ay eye", not "A <pause> I" or "aye"
    ("API", "[API](/ˌApˈiˈI/)"),                          # "ay pee eye", not "apey eye"
    ("APIs", "[APIs](/ˌApˈiˈIz/)"),
    ("IPv4", "[IPv4](/ˌIpˌivˈi fˈɔɹ/)"),                  # not "ipv four"
    ("IPv6", "[IPv6](/ˌIpˌivˈi sˈɪks/)"),
    ("2FA", "[2FA](/tˈu ˌɛfˈA/)"),                        # not "too far"
    ("JSON", "[JSON](/ʤˈAsᵊn/)"),                         # "jay-son", not spelled out
    ("SAML", "[SAML](/sˈæməl/)"),                         # "sam-el"
    ("LDAP", "[LDAP](/ˈɛldˌæp/)"),                        # "el-dap"
    ("SOC", "[SOC](/sˈɑk/)"),                             # "sock", not "soash"
    ("CISO", "[CISO](/sˈisO/)"),                          # "see-so"
    ("OWASP", "[OWASP](/ˈOwˌɑsp/)"),                      # "oh-wasp"
    ("DoS", "[DoS](/dˈɔs/)"),                             # "doss", not "doo-ess"
    ("SASE", "[SASE](/sˈæsi/)"),                          # "sassy"
    ("CASB", "[CASB](/kˈæzbˌi/)"),                        # "kaz-bee"
    ("FIPS", "[FIPS](/fˈɪps/)"),
    ("PaaS", "[PaaS](/pˈæs/)"),                           # "pass"
    ("PoC", "[PoC](/pˌiˌOsˈi/)"),                         # "P O C", not "posy"
    ("AWS", "[AWS](/ˌAdˌʌbᵊljuˈɛs/)"),                    # "A W S", not "awes"
    ("PostgreSQL", "[PostgreSQL](/pˈOstɡɹɛs kjˌuˈɛl/)"),  # "postgres Q L"
    ("OPSWAT", "[OPSWAT](/ˈɑpswˌɑt/)"),                   # "op swat", not spelled out
]


def default_dictionary():
    """The personal dictionary: used when --pronunciations isn't given and the file exists,
    and where --add-word (and the GUI's Use this) saves words. DECK_NARRATOR_DICTIONARY
    overrides where it lives."""
    env = os.environ.get("DECK_NARRATOR_DICTIONARY")
    if env:
        return Path(env)
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "deck-narrator" / "pronunciations.txt"


def dictionary_for(args):
    """The dictionary a run uses: --pronunciations, else the personal one if it exists."""
    if args.pronunciations:
        return Path(args.pronunciations)
    d = default_dictionary()
    return d if d.is_file() else None


def rules_for(args):
    """The dictionary a run uses (or None) and its rules, after the built-in ones."""
    dictionary = dictionary_for(args)
    return dictionary, BUILTIN_PRONUNCIATIONS + (load_pronunciations(dictionary) if dictionary else [])


def add_word(path, word, phonemes):
    """Save word=[word](/phonemes/) in the dictionary at path (created from DICT_TEMPLATE
    if missing). A rule for the same word is replaced where it is; otherwise it goes at
    the end. Comments and other rules are kept as they are."""
    word = word.strip()
    phonemes = phonemes.strip().strip("/")
    if not word or not re.fullmatch(r"[\w'’.-]+", word) or "=" in word:
        raise Fail(f"--add-word: {word!r} isn't a single word")
    if not phonemes or "/" in phonemes or ")" in phonemes:
        raise Fail(f"--add-word: {phonemes!r} isn't a usable phoneme string")
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else DICT_TEMPLATE.splitlines()
    if path.is_file():
        load_pronunciations(path)                 # refuse to rewrite a file that's already broken
    rule = f"{word}=[{word}](/{phonemes}/)"
    for i, line in enumerate(lines):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() == word:
            lines[i] = rule
            break
    else:
        lines.append(rule)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    log(f"Dictionary: {rule} saved in {path}")
    return 0


def load_pronunciations(path):
    rules = []
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Fail(f"{path}:{lineno}: expected word=replacement, got {raw!r}")
        word, repl = (s.strip() for s in line.split("=", 1))
        if not word:
            raise Fail(f"{path}:{lineno}: empty word")
        # Whole-word, case-sensitive: "SQL" and "sql" can be told apart.
        rules.append((word, repl))
    return rules


def apply_pronunciations(text, rules):
    """One pass over the text: every entry is matched against the original notes,
    longest entry first at each position, and a replacement is never re-scanned.
    Inline [word](...) overrides already in the notes are left alone, so they win."""
    if not rules:
        return text
    table = dict(rules)                       # a repeated word: the last line wins
    words = sorted(table, key=len, reverse=True)
    pattern = re.compile(r"(?P<override>\[[^\[\]]*\]\([^)]*\))|(?<!\w)(?:"
                         + "|".join(re.escape(w) for w in words) + r")(?!\w)")
    return pattern.sub(lambda m: m.group(0) if m.group("override") else table[m.group(0)], text)


def read_deck(deck_path, with_builds=True):
    """Return a list of dicts, one per slide in file order (hidden included)."""
    from pptx import Presentation
    try:
        prs = Presentation(str(deck_path))
    except Exception as e:
        raise Fail(f"could not open {deck_path} as a .pptx: {e}")
    slides = []
    for idx, slide in enumerate(prs.slides, 1):
        hidden = slide._element.get("show") == "0"
        notes = ""
        if slide.has_notes_slide:
            tf = slide.notes_slide.notes_text_frame
            notes = tf.text if tf is not None else ""
        b = anim.parse_builds(slide._element) if with_builds else anim.NO_BUILDS
        slides.append({"number": idx, "hidden": hidden, "raw_notes": notes, "builds": b,
                       "describe": (lambda el=slide._element, b=b: anim.describe(el, b))})
    return slides


def script_deck(slides, start_voice, rules):
    """Parse every visible slide's notes in deck order, so a [voice: ...] switch
    carries forward exactly as it would in a full render, even under --slides."""
    voice = start_voice
    for s in slides:
        if s["hidden"]:
            s.update(parts=[], clicks=0, text="")
            continue
        parts, s["clicks"], voice = parse_script(s["raw_notes"], voice, start_voice, s["number"], rules)
        s["parts"] = fold_parts(parts, len(s["builds"].states))
        s["text"] = " ".join(p["text"] for p in s["parts"])


def fold_parts(parts, n_states):
    """Clamp each part's step to the slide's last build state, then join neighbours
    that land on the same state with the same voice. A [click] on a slide with no
    builds (notes written for live presenting) then costs nothing: the text is
    voiced in one go, exactly as if the marker weren't there."""
    out = []
    for part in parts:
        step = min(part["step"], n_states - 1)
        if out and out[-1]["step"] == step and out[-1]["voice"] == part["voice"]:
            out[-1]["text"] += " " + part["text"]
        else:
            out.append({**part, "step": step})
    return out


# ---------------------------------------------------------------- timing

def plan_slide(s, build_hold):
    """Which build state is on screen while each part is spoken.

    Returns (steps, warnings). steps[k] = {"state": k, "parts": [...]} for every
    build state; text after the last build's click stays on the last state,
    and states the notes never click to get build_hold seconds each, after
    the narration (see segments_for).
    """
    n_states = len(s["builds"].states)
    steps = [{"state": k, "parts": []} for k in range(n_states)]
    for part in s["parts"]:
        steps[min(part["step"], n_states - 1)]["parts"].append(part)
    warnings = []
    if n_states > 1:
        clicks = s["clicks"]
        if clicks > n_states - 1:
            warnings.append(f"notes have {clicks} [click] but the slide has {n_states - 1} build step(s); "
                            f"text after click {n_states - 1} stays on the last build")
        elif clicks < n_states - 1:
            spare = n_states - 1 - clicks
            warnings.append(f"slide has {n_states - 1} build step(s) but the notes have {clicks} [click]; "
                            f"the last {spare} play after the narration, {build_hold:g}s each")
        if not s["parts"]:
            warnings = []           # no notes: builds just play through, see segments_for
    return steps, warnings


# ---------------------------------------------------------------- tools

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
INSTALL_HINT = {
    "ffmpeg": ("winget install Gyan.FFmpeg  (then open a new terminal)" if IS_WINDOWS
               else "brew install ffmpeg" if IS_MAC
               else "sudo apt-get install ffmpeg"),
    "soffice": ("Microsoft PowerPoint or LibreOffice is needed to draw the slides. Run install-dependencies.cmd "
                "in the Deck Narrator folder for a minimal LibreOffice that leaves Office's file types alone, or get "
                "it from https://www.libreoffice.org/download/" if IS_WINDOWS
                else "brew install --cask libreoffice" if IS_MAC
                else "sudo apt-get install libreoffice-impress"),
}


def app_dir():
    """Where the program's bundled files (ffmpeg/, model/, samples/) live: next to the .exe
    when frozen, Contents/Resources inside the Mac app, else this file's folder."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    exe_dir = Path(sys.executable).parent
    if IS_MAC and exe_dir.name == "MacOS":
        return exe_dir.parent / "Resources"
    return exe_dir


def find_ffmpeg():
    """DECK_NARRATOR_FFMPEG, else the copy the Windows builds ship in ffmpeg/, else PATH."""
    bundled = app_dir() / "ffmpeg" / ("ffmpeg.exe" if IS_WINDOWS else "ffmpeg")
    path = (os.environ.get("DECK_NARRATOR_FFMPEG") or (str(bundled) if bundled.is_file() else None)
            or shutil.which("ffmpeg"))
    if not path or not Path(path).exists():
        raise Fail(f"ffmpeg not found on PATH (or set DECK_NARRATOR_FFMPEG). Install it: {INSTALL_HINT['ffmpeg']}")
    return path


def find_soffice():
    """LibreOffice's command-line entry point. On Windows it's usually not on PATH,
    and soffice.com (the console wrapper, which waits for the conversion to finish)
    is the one to run, not soffice.exe."""
    candidates = [os.environ.get("DECK_NARRATOR_SOFFICE")]
    if IS_WINDOWS:
        candidates += [shutil.which("soffice.com"), shutil.which("soffice")]
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidates += [str(Path(root) / "LibreOffice" / "program" / n) for n in ("soffice.com", "soffice.exe")]
    else:
        candidates += [shutil.which("soffice"), shutil.which("libreoffice")]
        if IS_MAC:
            candidates += [str(Path(root) / "LibreOffice.app" / "Contents" / "MacOS" / "soffice")
                           for root in ("/Applications", Path.home() / "Applications")]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise Fail(f"LibreOffice (soffice) not found (or set DECK_NARRATOR_SOFFICE). Install it: {INSTALL_HINT['soffice']}")


def powerpoint_installed():
    """True when Microsoft PowerPoint is installed (its COM automation is registered)."""
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"PowerPoint.Application\CLSID"))
        return True
    except OSError:
        return False


def keynote_installed():
    """True on a Mac with Apple's Keynote (free, and it opens .pptx)."""
    return IS_MAC and any((Path(root) / "Keynote.app").is_dir()
                          for root in ("/Applications", Path.home() / "Applications"))


def choose_renderer(choice):
    """--renderer -> "powerpoint", "keynote" or "libreoffice", checking the one picked is there.
    auto prefers PowerPoint on Windows: it draws a deck exactly as PowerPoint shows it, and on
    a PC with Office it means LibreOffice isn't needed at all. On a Mac, auto prefers Keynote,
    which every Mac can have for free."""
    choice = os.environ.get("DECK_NARRATOR_RENDERER") or choice
    if choice in ("auto", "powerpoint") and powerpoint_installed():
        return "powerpoint"
    if choice == "powerpoint":
        raise Fail("--renderer powerpoint: Microsoft PowerPoint isn't installed on this PC "
                   "(on a Mac, use Keynote)" if IS_MAC else
                   "--renderer powerpoint: Microsoft PowerPoint isn't installed on this PC")
    if choice in ("auto", "keynote") and keynote_installed():
        return "keynote"
    if choice == "keynote":
        raise Fail("--renderer keynote: Keynote isn't installed (it's free in the Mac App Store)")
    find_soffice()
    return "libreoffice"


def run(cmd, what):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-15:])
        raise Fail(f"{what} failed (exit {r.returncode}):\n{tail}")
    return r


# ---------------------------------------------------------------- rendering

# Exports the listed slides of a deck to PNGs through PowerPoint's own renderer. It
# opens the deck read-only and windowless, and quits PowerPoint afterwards only if it
# wasn't already running (so an open PowerPoint, and the user's decks, are left alone).
PPT_EXPORT = r"""
param([string]$Deck, [string]$OutDir, [string]$Slides, [int]$Long)
$ErrorActionPreference = "Stop"
$wasRunning = [bool](Get-Process POWERPNT -ErrorAction SilentlyContinue)
$app = New-Object -ComObject PowerPoint.Application
$pres = $null
try {
    $pres = $app.Presentations.Open($Deck, -1, 0, 0)    # ReadOnly, not Untitled, no window
    $w = $pres.PageSetup.SlideWidth; $h = $pres.PageSetup.SlideHeight
    $k = $Long / [Math]::Max($w, $h)
    $pw = [int][Math]::Round($w * $k); $ph = [int][Math]::Round($h * $k)
    foreach ($n in $Slides.Split(",")) {
        $pres.Slides.Item([int]$n).Export((Join-Path $OutDir "s-$n.png"), "PNG", $pw, $ph)
    }
} finally {
    if ($pres) { $pres.Close() }
    if (-not $wasRunning -and $app.Presentations.Count -eq 0) { $app.Quit() }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
"""


def export_powerpoint(deck_path, outdir, pages):
    """PNGs of slides `pages` (1-based) of deck_path, drawn by PowerPoint, in that order.
    Hidden slides export like any other, so no hidden-slide bookkeeping is needed."""
    outdir.mkdir(parents=True, exist_ok=True)
    script = outdir / "export.ps1"
    script.write_text(PPT_EXPORT, encoding="utf-8-sig")
    run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Deck", str(deck_path.resolve()), "-OutDir", str(outdir.resolve()),
         "-Slides", ",".join(str(n) for n in pages), "-Long", str(WIDTH)], "PowerPoint export")
    pngs = [outdir / f"s-{n}.png" for n in pages]
    missing = [p.name for p in pngs if not p.is_file()]
    if missing:
        raise Fail(f"PowerPoint reported success but didn't write {', '.join(missing)}")
    return pngs


# Exports a deck to PDF through Keynote, which opens .pptx itself. Hidden slides come in as
# Keynote's skipped slides. Keynote is quit afterwards only if it wasn't already running.
KEYNOTE_EXPORT = r"""
on run argv
    set deckFile to POSIX file (item 1 of argv)
    set pdfFile to POSIX file (item 2 of argv)
    set withSkipped to (item 3 of argv) is "1"
    tell application "System Events" to set wasRunning to exists (processes where bundle identifier is "com.apple.iWork.Keynote")
    tell application "Keynote"
        set d to open deckFile
        try
            export d to pdfFile as PDF with properties {PDF image quality:Best, skipped slides:withSkipped}
        on error msg number n
            close d saving no
            error msg number n
        end try
        close d saving no
        if not wasRunning then quit
    end tell
end run
"""


def export_keynote(deck_path, outdir, include_hidden):
    """The deck as a PDF drawn by Keynote; hidden slides are included only if asked."""
    outdir.mkdir(parents=True, exist_ok=True)
    script = outdir / "export.applescript"
    script.write_text(KEYNOTE_EXPORT, encoding="utf-8")
    pdf = outdir / (deck_path.stem + ".pdf")
    run(["osascript", str(script), str(deck_path.resolve()), str(pdf.resolve()), "1" if include_hidden else "0"],
        "Keynote export (if macOS asked whether Deck Narrator may control Keynote, allow it and try again)")
    if not pdf.exists():
        raise Fail(f"Keynote reported success but wrote no PDF at {pdf}")
    return pdf


def export_pdf(deck_path, outdir, profile, include_hidden):
    soffice = find_soffice()
    filt = json.dumps({"ExportHiddenSlides": {"type": "boolean", "value": "true" if include_hidden else "false"},
                       "ExportNotesPages": {"type": "boolean", "value": "false"}})
    run([soffice, f"-env:UserInstallation={profile.resolve().as_uri()}", "--headless", "--norestore",
         "--convert-to", f"pdf:impress_pdf_Export:{filt}", "--outdir", str(outdir), str(deck_path)],
        "LibreOffice PDF export")
    pdf = outdir / (deck_path.stem + ".pdf")
    if not pdf.exists():
        raise Fail(f"LibreOffice reported success but wrote no PDF at {pdf}")
    return pdf


def rasterize(pdf, prefix, expected):
    """PDF pages -> PNGs, 1920px on the long side (pypdfium2: no poppler needed)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        if len(doc) != expected:
            raise Fail(f"PDF has {len(doc)} pages but {expected} were expected; "
                       "can't map pages to slides safely.")
        pngs = []
        for i in range(len(doc)):
            page = doc[i]
            w, h = page.get_size()
            image = page.render(scale=WIDTH / max(w, h)).to_pil()
            png = prefix.with_name(f"{prefix.name}-{i + 1}.png")
            image.save(png)
            pngs.append(png)
            page.close()
        return pngs
    finally:
        doc.close()


def render_states(deck_path, tmp, slides, selected, renderer="libreoffice"):
    """PNG for every (slide number, build state) the video needs.

    Without builds this is one LibreOffice export of the deck as-is (hidden
    slides included, so page N is slide N). With builds, pass v renders
    build state v of every selected slide that has one, from an edited copy
    of the deck; slides not needed in that pass are marked hidden and left
    out of the PDF, so its pages are exactly the slides we asked for, in order.
    Passes = 1 + the most clicks on any one slide, not one per build state.
    With PowerPoint, each pass exports exactly those slides' pictures instead of a PDF.
    """
    from pptx import Presentation
    profile = tmp / "lo-profile"
    tool = {"powerpoint": "PowerPoint", "keynote": "Keynote"}.get(renderer, "LibreOffice")
    n_passes = max(len(s["builds"].states) for s in selected)
    animated = [s for s in selected if len(s["builds"].states) > 1 or s["builds"].states[0]]
    out = {}
    for v in range(n_passes):
        if v == 0 and not animated:
            deck, include_hidden, pages = deck_path, True, [s["number"] for s in slides]
            log(f"Rendering deck with {tool}...")
        else:
            prs = Presentation(str(deck_path))
            pages = []
            by_number = {s["number"]: s for s in selected}
            for num, slide in enumerate(prs.slides, 1):
                s = by_number.get(num)
                states = s["builds"].states if s else []
                if v == 0:
                    pages.append(num)               # pass 0 keeps every slide, page N = slide N
                    if states:
                        anim.apply_state(slide._element, states[0])
                elif len(states) > v:
                    slide._element.attrib.pop("show", None)
                    anim.apply_state(slide._element, states[v])
                    pages.append(num)
                else:
                    slide._element.set("show", "0")
            passdir = tmp / f"pass{v}"
            passdir.mkdir()
            deck = passdir / deck_path.name
            prs.save(str(deck))
            include_hidden = v == 0
            log(f"Rendering build pass {v + 1}/{n_passes} with {tool}...")
        if renderer == "powerpoint":
            pngs = export_powerpoint(deck, tmp / f"ppt{v}", pages)
        elif renderer == "keynote":
            pngs = rasterize(export_keynote(deck, tmp / f"key{v}", include_hidden), tmp / f"p{v}", len(pages))
        else:
            pngs = rasterize(export_pdf(deck, tmp / f"pdf{v}", profile, include_hidden), tmp / f"p{v}", len(pages))
        for num, png in zip(pages, pngs):
            out[(num, v)] = png
    return out


# ---------------------------------------------------------------- TTS

def split_sentences(text):
    """Split at sentence ends, then pack sentences into <= CHUNK_CHARS chunks."""
    sentences = [s for s in re.split(r"(?<=[.!?…])[\"')\]]*\s+", text) if s.strip()]
    pieces = []
    for s in sentences:
        # A single run-on "sentence" longer than the limit: break at commas/
        # semicolons, then at spaces as a last resort. Never drop words.
        while len(s) > CHUNK_CHARS:
            cut = max(s.rfind(sep, 0, CHUNK_CHARS) for sep in (", ", "; ", ": ", " - "))
            if cut <= 0:
                cut = s.rfind(" ", 0, CHUNK_CHARS)
            if cut <= 0:
                cut = CHUNK_CHARS
            pieces.append(s[:cut + 1].strip())
            s = s[cut + 1:].strip()
        if s:
            pieces.append(s)
    chunks, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + 1 + len(piece) > CHUNK_CHARS:
            chunks.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def local_model_dir():
    """A bundled copy of the model and voices, so nothing is downloaded: the folder in
    DECK_NARRATOR_MODEL_DIR, else model/ next to the program (the Windows installer puts
    one there). It needs config.json, kokoro-v1_0.pth and voices/*.pt. None = use the
    HuggingFace download and cache, as before."""
    env = os.environ.get("DECK_NARRATOR_MODEL_DIR")
    for d in ([Path(env)] if env else []) + [app_dir() / "model"]:
        if (d / "config.json").is_file() and (d / "kokoro-v1_0.pth").is_file():
            return d
    if env:
        raise Fail(f"DECK_NARRATOR_MODEL_DIR={env} has no config.json and kokoro-v1_0.pth")
    return None


def user_voice_dir():
    """Where --update-voices puts new and updated voices: per user, so no admin rights
    are needed and the installed copy is never modified. DECK_NARRATOR_VOICE_DIR overrides."""
    env = os.environ.get("DECK_NARRATOR_VOICE_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "deck-narrator" / "voices"


def local_voice_files():
    """Voice name -> .pt file on this machine: the bundled voices, overridden by
    downloaded ones (newer, or not bundled at all)."""
    found = {}
    d = local_model_dir()
    for folder in ([d / "voices"] if d else []) + [user_voice_dir()]:
        if folder.is_dir():
            found.update({p.stem: p for p in folder.glob("*.pt")})
    return found


def voice_ref(voice):
    """What Kokoro loads for a voice: a local .pt file if there is one, else its name
    (downloaded from HuggingFace)."""
    p = local_voice_files().get(voice)
    return str(p) if p else voice


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def update_voices():
    """--update-voices: fetch voices that are new on HuggingFace, or that changed since
    the copy here was made, into user_voice_dir(). Never fails a run for being offline.
    Prints one summary line on stdout, starting "voices:", for the GUI to read."""
    if not local_model_dir():
        log("This install loads voices from HuggingFace by name, so they're always current.")
        print("voices: not bundled")
        return 0
    try:
        from huggingface_hub import HfApi, hf_hub_download
        remote = {Path(f.path).stem: f for f in HfApi().list_repo_tree(REPO_ID, path_in_repo="voices")
                  if f.path.endswith(".pt")}
    except Exception as e:
        log(f"Voice check skipped: couldn't reach HuggingFace ({type(e).__name__}). The voices here still work.")
        print("voices: offline")
        return 0
    have = local_voice_files()
    new, changed = [], []
    for name, f in sorted(remote.items()):
        sha = getattr(getattr(f, "lfs", None), "sha256", None)
        if name not in have:
            new.append(name)
        elif sha and sha256_file(have[name]) != sha:
            changed.append(name)
    dest = user_voice_dir()
    for name in new + changed:
        try:
            src = Path(hf_hub_download(REPO_ID, f"voices/{name}.pt"))
            dest.mkdir(parents=True, exist_ok=True)
            part = dest / f"{name}.pt.part"
            shutil.copyfile(src, part)
            part.replace(dest / f"{name}.pt")
            log(f"  {'new' if name in new else 'updated'}: {name}")
        except Exception as e:
            log(f"  couldn't download {name}: {type(e).__name__}: {e}")
            (new if name in new else changed).remove(name)
    current = len(remote) - len(new) - len(changed)
    log(f"Voices: {len(new)} new, {len(changed)} updated, {current} already current (in {dest})")
    print(f"voices: {len(new)} new{' (' + ', '.join(new) + ')' if new else ''}; "
          f"{len(changed)} updated{' (' + ', '.join(changed) + ')' if changed else ''}")
    return 0


def available_voices():
    """Voices the GUI offers: the built-in English list plus any local English voices.
    (Other languages need extra phonemizer packages that aren't installed.)"""
    names = set(KNOWN_VOICES) | {v for v in local_voice_files() if v[:1] in ("a", "b")}
    return sorted(own_voices()) + sorted(v for v in names if is_kokoro_name(v))


def mps_available(torch):
    """Apple Silicon's GPU (Metal), as torch sees it."""
    return getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()


def resolve_device(choice):
    import torch
    if choice == "cuda" and not torch.cuda.is_available():
        raise Fail("--device cuda requested but CUDA is not available to torch")
    if choice == "mps" and not mps_available(torch):
        raise Fail("--device mps requested but Apple's Metal GPU is not available to torch")
    if choice == "auto":
        return "cuda" if torch.cuda.is_available() else "mps" if mps_available(torch) else "cpu"
    return choice


class TTS:
    """One Kokoro model, shared by a phonemizer pipeline per language (American and British
    English need different ones), voices loaded on demand; plus your own voices, spoken by
    Chatterbox. Each engine starts the first time one of its voices is used."""

    def __init__(self, device):
        self.device = device
        self.model = None
        self.pipes = {}
        self.own = None
        self.speed_noted = False

    def kokoro(self):
        if self.model is not None:
            return self.model
        import warnings
        warnings.filterwarnings("ignore")
        try:
            from kokoro import KModel
        except ImportError as e:
            raise Fail(f"kokoro isn't installed in this Python ({sys.executable}): {e}. Run setup.sh.")
        local = local_model_dir()
        log(f"Loading Kokoro-82M on {self.device}{f' from {local}' if local else ''}...")
        try:
            if local:
                self.model = KModel(repo_id=REPO_ID, config=str(local / "config.json"),
                                    model=str(local / "kokoro-v1_0.pth")).to(self.device).eval()
            else:
                self.model = KModel(repo_id=REPO_ID).to(self.device).eval()
        except Exception as e:
            raise Fail(f"could not load the Kokoro model from HuggingFace ({REPO_ID}): "
                       f"{type(e).__name__}: {e}\nCheck network access.")
        return self.model

    def pipe(self, voice, where="--voice"):
        """Get a voice ready to speak (and fail early, with where, if it can't)."""
        check_voice_name(voice, where)
        if is_own_voice(voice):
            if self.own is None:
                self.own = OwnVoice(self.device)
            self.own.load(voice)
            return None
        from kokoro import KPipeline
        lang = voice[0]
        try:
            if lang not in self.pipes:
                self.pipes[lang] = KPipeline(lang_code=lang, repo_id=REPO_ID, model=self.kokoro())
            self.pipes[lang].load_voice(voice_ref(voice))
        except ModuleNotFoundError as e:
            raise Fail(f"{where}: voice {voice!r} ({LANG_NAMES[lang]}) needs an extra package that isn't installed: "
                       f"{e}. English voices (a*/b*) work out of the box.")
        except Exception as e:
            raise Fail(f"{where}: could not load voice {voice!r} from HuggingFace ({REPO_ID}): "
                       f"{type(e).__name__}: {e}\nCheck network access, or run --list-voices to check the name.")
        return self.pipes[lang]

    def synthesize(self, voice, text, speed):
        import numpy as np
        pipe = self.pipe(voice)
        out = []
        gap = np.zeros(int(CHUNK_GAP * SAMPLE_RATE), dtype=np.float32)
        if pipe is None and speed != 1.0 and not self.speed_noted:
            log("Note: speed applies to the built-in voices only; your own voice speaks at its natural pace.")
            self.speed_noted = True
        for chunk in split_sentences(plain_text(text) if pipe is None else text):
            if pipe is None:
                parts = [self.own.say(voice, chunk)]
            else:
                parts = []
                for result in pipe(chunk, voice=voice_ref(voice), speed=speed, split_pattern=None):
                    if result.audio is not None:
                        parts.append(result.audio.detach().cpu().numpy().astype(np.float32))
            if not parts or not sum(len(p) for p in parts):
                raise Fail(f"{'Chatterbox' if pipe is None else 'Kokoro'} produced no audio for: {chunk[:80]!r}")
            if out:
                out.append(gap)
            out.extend(parts)
        return np.concatenate(out)

    def close(self):
        if self.own is not None:
            self.own.close()
            self.own = None


def speech_level(audio):
    """RMS of the parts of a clip that are actually speech (20 ms frames above -45 dBFS)."""
    import numpy as np
    n = len(audio) // 480 * 480
    if n == 0:
        return 0.0
    frames = audio[:n].reshape(-1, 480)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    active = rms[rms > 10 ** (-45 / 20)]
    return float(np.sqrt((active ** 2).mean())) if len(active) else 0.0


def level_voices(clips):
    """Bring every voice to the same speech level before the deck-wide loudnorm,
    so a voice switch doesn't sound like someone touched the volume.
    clips: list of (voice, ndarray), scaled in place. Returns {voice: gain}."""
    import numpy as np
    by_voice = {}
    for voice, audio in clips:
        by_voice.setdefault(voice, []).append(audio)
    if len(by_voice) < 2:
        return {}
    levels = {v: speech_level(np.concatenate(a)) for v, a in by_voice.items()}
    target = float(np.median([l for l in levels.values() if l > 0]))
    gains = {v: (target / l if l > 0 else 1.0) for v, l in levels.items()}
    for voice, audio in clips:
        audio *= gains[voice]
    return gains


def list_voices():
    local = local_model_dir()
    try:
        if local:
            voices = sorted(local_voice_files())
            if not voices:
                raise FileNotFoundError(local / "voices")
            print_voices(voices, f"on this machine: {local / 'voices'} and {user_voice_dir()}")
            return
        from huggingface_hub import list_repo_files
        voices = sorted(f[len("voices/"):-3] for f in list_repo_files(REPO_ID)
                        if f.startswith("voices/") and f.endswith(".pt"))
        source = REPO_ID
    except Exception as e:
        voices, source = KNOWN_VOICES, f"built-in list (HuggingFace unreachable: {type(e).__name__})"
    print_voices(voices, source)
    own = own_voices()
    if own:
        state = "ready" if own_voice_ready() else "not set up yet: run --install-own-voice"
        print(f"Your own voices ({my_voices_dir()}; Chatterbox {state}):")
        for name, d in own.items():
            print(f"  {name:<16} {'fine-tuned' if (d / 't3.safetensors').is_file() else 'from a recording'}")


def print_voices(voices, source):
    print(f"Kokoro voices ({source}). Prefix: 1st letter = language, 2nd = f/m.")
    for v in voices:
        mark = "  (default)" if v == DEFAULT_VOICE else ""
        print(f"  {v:<16} {LANG_NAMES.get(v[0], '?')}{mark}")
    print("English voices (a*/b*) work out of the box; other languages may need extra misaki packages.")


# ---------------------------------------------------------------- your own voice (Chatterbox)
#
# Optional. --install-own-voice sets up Chatterbox (Resemble AI, MIT) in its own Python
# environment under data_home()/chatterbox, because it needs a different torch and
# transformers than Kokoro. A voice is a folder in my_voices_dir() with a recording of the
# speaker (reference.wav) and, if someone fine-tuned it, t3.safetensors and voice.json.
# own_voice_worker.py runs in that environment and does the speaking.

CHATTERBOX = "chatterbox-tts==0.1.7"
CHATTERBOX_TORCH = "2.8.0"             # 0.1.7 pins 2.6.0, which can't use RTX 50-series GPUs
OWN_PYTHON = "3.11"
# uv, the installer that builds the environment: a pinned release from PyPI, checked by hash.
UV_WHEELS = {
    "win": ("https://files.pythonhosted.org/packages/1f/72/c98ecbe0c4dbaf9118776053688a43dfca5708d86223cf3aa5d38066df21/"
            "uv-0.12.20-py3-none-win_amd64.whl",
            "1502e03f4da3280cbb493d356d59bdd401bf23197cd71df64e1c6feac156090c"),
    "linux": ("https://files.pythonhosted.org/packages/83/35/8a0bfb4065abc017dc72f39591683cc9e264e2653cf808338aac4865c063/"
              "uv-0.12.20-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
              "d0837cb0ec80f830198e4a0fe86385e2a8ba8846f066acd243a1c15f4d52ca74"),
    "mac": ("https://files.pythonhosted.org/packages/95/02/857f98f06d91a9c932e04d911367623134dfc941968d7d039678287172e9/"
            "uv-0.12.20-py3-none-macosx_11_0_arm64.whl",
            "08ca4588bac6a4bb8972236c0958aaa0ebea7b2045289edbf85f9a21f44db979"),
}
OWN_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
AUDIO_EXTS = (".wav", ".flac", ".mp3", ".ogg")


def data_home():
    """Per-user data: %LOCALAPPDATA%\\deck-narrator, else $XDG_DATA_HOME/deck-narrator."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "deck-narrator"


def own_voice_home():
    """Chatterbox's environment, model and installer. DECK_NARRATOR_OWN_VOICE_HOME overrides."""
    env = os.environ.get("DECK_NARRATOR_OWN_VOICE_HOME")
    return Path(env) if env else data_home() / "chatterbox"


def my_voices_dir():
    """Your own voices, one folder each. DECK_NARRATOR_MY_VOICES overrides."""
    env = os.environ.get("DECK_NARRATOR_MY_VOICES")
    return Path(env) if env else data_home() / "my-voices"


def own_python():
    venv = own_voice_home() / "venv"
    return venv / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def own_voice_ready():
    return (own_voice_home() / "ready.json").is_file() and own_python().is_file()


def own_voices():
    """Your own voices: name -> folder (one that has a reference recording)."""
    d = my_voices_dir()
    if not d.is_dir():
        return {}
    return {p.name: p for p in sorted(d.iterdir())
            if p.is_dir() and OWN_NAME.fullmatch(p.name) and any((p / f"reference{e}").is_file() for e in AUDIO_EXTS)}


def is_kokoro_name(name):
    return bool(re.fullmatch(r"[a-z][fm]_[a-z0-9_]+", name))


def is_own_voice(name):
    return not is_kokoro_name(name) and name in own_voices()


def worker_script():
    """own_voice_worker.py: next to narrate.py, or in the frozen app's bundled files."""
    for d in (Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else None,
              Path(__file__).resolve().parent, app_dir()):
        if d and (d / "own_voice_worker.py").is_file():
            return d / "own_voice_worker.py"
    raise Fail("own_voice_worker.py is missing from this install; reinstall Deck Narrator")


def child_env(**extra):
    """The environment for a program that isn't this one: without what a frozen build sets
    for itself (Python paths, its private library folder), so another Python works normally."""
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
        env.pop(k, None)
    for k in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        if f"{k}_ORIG" in env:
            env[k] = env.pop(f"{k}_ORIG")
        elif getattr(sys, "frozen", False):
            env.pop(k, None)
    env["HF_HOME"] = str(own_voice_home() / "hf")
    env["PYTHONIOENCODING"] = "utf-8"
    env.update({k: str(v) for k, v in extra.items()})
    return env


def fetch_uv(home):
    """uv, from the pinned PyPI wheel (hash checked), into home/uv/."""
    import hashlib
    import urllib.request
    import zipfile
    key = "win" if IS_WINDOWS else "mac" if IS_MAC else "linux"
    import platform
    machine = platform.machine().lower()
    if (key == "mac" and machine != "arm64") or (key != "mac" and machine not in ("amd64", "x86_64")):
        raise Fail(f"your own voice needs a 64-bit Intel/AMD PC or an Apple Silicon Mac (this is {machine})")
    exe = home / "uv" / ("uv.exe" if IS_WINDOWS else "uv")
    if exe.is_file():
        return exe
    url, sha = UV_WHEELS[key]
    log(f"Downloading the installer (uv) from {url.split('/')[2]}...")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            blob = r.read()
    except OSError as e:
        raise Fail(f"couldn't download uv: {e}. Check your internet connection.")
    if hashlib.sha256(blob).hexdigest() != sha:
        raise Fail("the downloaded uv doesn't match its expected hash; not using it")
    tmp = home / "uv.whl.part"
    tmp.write_bytes(blob)
    with zipfile.ZipFile(tmp) as z:
        name = next(n for n in z.namelist() if n.endswith("/scripts/" + exe.name))
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(z.read(name))
    tmp.unlink()
    exe.chmod(0o755)
    return exe


def torch_backend():
    """Which torch to install: NVIDIA's CUDA 12.8 build when an NVIDIA driver is here,
    else the CPU build; on a Mac, the standard one (it uses Metal).
    DECK_NARRATOR_TORCH_BACKEND overrides (cpu, cu128, ...)."""
    if os.environ.get("DECK_NARRATOR_TORCH_BACKEND"):
        return os.environ["DECK_NARRATOR_TORCH_BACKEND"]
    if IS_MAC:
        return None
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            if subprocess.run([smi, "-L"], capture_output=True, timeout=30).returncode == 0:
                return "cu128"
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "cpu"


def install_own_voice():
    """--install-own-voice: set up Chatterbox in its own environment and download its model.
    Safe to run again: it repairs or updates what's there."""
    home = own_voice_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "ready.json").unlink(missing_ok=True)
    uv = fetch_uv(home)
    env = child_env(UV_PYTHON_INSTALL_DIR=home / "python", UV_CACHE_DIR=home / "uv-cache",
                    UV_LINK_MODE="copy", UV_PYTHON_PREFERENCE="only-managed")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}

    def step(what, cmd):
        log(what)
        try:
            code = subprocess.run([str(c) for c in cmd], env=env, stdin=subprocess.DEVNULL,
                                  stdout=sys.stderr, stderr=sys.stderr, **flags).returncode
        except OSError as e:
            raise Fail(f"{what.rstrip('.')} failed: {e}")
        if code:
            raise Fail(f"{what.rstrip('.')} failed (exit code {code}); the lines above say why. "
                       "Running it again picks up where it stopped.")

    if not own_python().is_file():
        step(f"Making a Python {OWN_PYTHON} environment...", [uv, "venv", "--python", OWN_PYTHON, home / "venv"])
    backend = torch_backend()
    overrides = home / "overrides.txt"
    # setuptools 81+ dropped pkg_resources, which Chatterbox's watermarker (resemble-perth)
    # imports; without it the model doesn't load.
    overrides.write_text(f"torch=={CHATTERBOX_TORCH}\ntorchaudio=={CHATTERBOX_TORCH}\nsetuptools<81\n", encoding="utf-8")
    cmd = [uv, "pip", "install", "--python", own_python(), "--override", overrides, CHATTERBOX, "soundfile"]
    if backend:
        cmd[3:3] = ["--torch-backend", backend]
    what = {"cpu": "for the processor", None: "for Apple Silicon"}.get(backend, f"for NVIDIA GPUs ({backend})")
    step(f"Installing Chatterbox and torch {what}. This downloads 1 to 3 GB...", cmd)
    step("Downloading the Chatterbox model (about 3 GB) and checking it loads...",
         [own_python(), "-I", worker_script(), "--prefetch"])
    shutil.rmtree(home / "uv-cache", ignore_errors=True)
    (home / "ready.json").write_text(json.dumps({"deck_narrator": VERSION, "package": CHATTERBOX,
                                                 "torch": CHATTERBOX_TORCH, "backend": backend or "default"}),
                                     encoding="utf-8")
    log(f"Your own voice is set up (in {home}). Add a voice with --add-voice NAME RECORDING, "
        "or Settings > Add a voice.")
    print("own-voice: ready")
    return 0


def add_voice(name, src):
    """--add-voice NAME FILE: a recording (.wav, .flac, .mp3) or a voice pack (.zip or a
    folder with reference.wav and maybe t3.safetensors and voice.json) becomes a voice."""
    import zipfile
    name = name.strip().lower()
    if not OWN_NAME.fullmatch(name) or is_kokoro_name(name) or name == "default":
        raise Fail(f"--add-voice: {name!r} can't be a voice name. Use up to 32 lowercase letters, digits, - or _, "
                   "like mike or jane-doe (and not the af_/am_ style of the built-in voices).")
    src = Path(src).expanduser()
    if not src.exists():
        raise Fail(f"--add-voice: no such file: {src}")
    staging = Path(tempfile.mkdtemp(prefix="deck-narrator-voice-"))
    try:
        if src.is_dir() or src.suffix.lower() == ".zip":
            z = None if src.is_dir() else zipfile.ZipFile(src)
            files = ({p.name: p for p in src.iterdir() if p.is_file()} if z is None else
                     {Path(n).name: n for n in z.namelist() if not n.endswith("/")})

            def copy(n, dest):                  # streamed: a fine-tuned model is most of a GB
                with (open(files[n], "rb") if z is None else z.open(files[n])) as f, open(dest, "wb") as out:
                    shutil.copyfileobj(f, out, 1 << 20)
                return dest
            refs = [n for n in files if n.lower().startswith("reference.") and n.lower().endswith(AUDIO_EXTS)] \
                or [n for n in files if n.lower().endswith(AUDIO_EXTS)]
            if len(refs) != 1:
                raise Fail(f"--add-voice: {src.name} needs exactly one recording (reference.wav); found {len(refs)}")
            copy(refs[0], staging / ("reference" + Path(refs[0]).suffix.lower()))
            models = [n for n in files if n.endswith(".safetensors")]
            if len(models) > 1:
                raise Fail(f"--add-voice: {src.name} has {len(models)} .safetensors files; a voice pack has one (t3.safetensors)")
            if models:
                copy(models[0], staging / "t3.safetensors")
            if "voice.json" in files:
                settings = json.loads(copy("voice.json", staging / "voice.json").read_text(encoding="utf-8"))
                keep = {k: float(settings[k]) for k in ("exaggeration", "cfg_weight", "temperature") if k in settings}
                (staging / "voice.json").write_text(json.dumps(keep, indent=2), encoding="utf-8")
            if z is not None:
                z.close()
        elif src.suffix.lower() in AUDIO_EXTS:
            shutil.copyfile(src, staging / ("reference" + src.suffix.lower()))
        else:
            raise Fail(f"--add-voice: {src.name} isn't a recording (.wav, .flac, .mp3) or a voice pack (.zip)")
        ref = next(staging.glob("reference.*"))
        try:
            import soundfile as sf
            info = sf.info(str(ref))
            seconds = info.frames / info.samplerate
        except Exception as e:
            raise Fail(f"--add-voice: can't read the recording {ref.name}: {e}")
        if seconds < 5:
            raise Fail(f"--add-voice: the recording is {seconds:.1f}s; use 10 to 30 seconds of the person talking")
        if seconds > 60:
            log(f"Note: the recording is {seconds:.0f}s; Chatterbox uses its first 10 seconds.")
        dest = my_voices_dir() / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staging, dest)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    tuned = " with its fine-tuned model" if (dest / "t3.safetensors").is_file() else ""
    log(f"Voice {name!r} added{tuned} ({dest}). Use it with --voice {name} or [voice: {name}].")
    if not own_voice_ready():
        log("It speaks once your own voice is set up: --install-own-voice, or Settings > Set up.")
    print(f"voice: {name}")
    return 0


def remove_voice(name):
    d = own_voices().get(name.strip().lower())
    if not d:
        raise Fail(f"--remove-voice: there's no voice of your own called {name!r}")
    shutil.rmtree(d)
    log(f"Voice {d.name!r} removed.")
    return 0


PHONEME_OVERRIDE = re.compile(r"\[([^\[\]]+)\]\((?:/[^)]*/|[+-]?\d(?:\.5)?)\)")


def plain_text(text):
    """Kokoro's inline [word](/phonemes/) overrides back to the word: Chatterbox reads text."""
    return PHONEME_OVERRIDE.sub(r"\1", text)


def text_seed(voice, text):
    """A fixed seed per voice and sentence, so the same notes always sound the same."""
    import hashlib
    return int(hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()[:8], 16)


def trim_edges(audio, margin=0.05):
    """Drop the silence a generated clip starts or ends with (Kokoro's clips have none)."""
    import numpy as np
    frame = int(SAMPLE_RATE * 0.01)
    n = len(audio) // frame
    if n == 0:
        return audio
    rms = np.sqrt((audio[:n * frame].reshape(n, frame) ** 2).mean(axis=1))
    loud = np.nonzero(rms > 10 ** (-50 / 20))[0]
    if not len(loud):
        return audio
    keep = int(margin * SAMPLE_RATE)
    return audio[max(0, loud[0] * frame - keep):min(len(audio), (loud[-1] + 1) * frame + keep)]


class OwnVoice:
    """own_voice_worker.py, running in Chatterbox's environment for the length of a run."""

    def __init__(self, device):
        if not own_voice_ready():
            raise Fail("your own voice isn't set up yet. Run deck-narrator --install-own-voice "
                       "(or Settings > Set up in the app), then try again.")
        log("Starting Chatterbox for your own voice...")
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}
        self.proc = subprocess.Popen(
            [str(own_python()), "-I", str(worker_script()), "--device", device],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr, text=True, encoding="utf-8",
            env=child_env(HF_HUB_OFFLINE="1", PYTORCH_ENABLE_MPS_FALLBACK="1"), **flags)
        hello = self.reply()
        if not hello.get("ready"):
            raise Fail(f"Chatterbox didn't start: {hello.get('error', hello)}")
        if hello.get("sr") != SAMPLE_RATE:
            raise Fail(f"Chatterbox speaks at {hello.get('sr')} Hz; this version of deck-narrator expects {SAMPLE_RATE}")
        log(f"Chatterbox is running on {hello.get('device')}.")
        self.loaded = None
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-narrator-own-"))

    def reply(self):
        line = self.proc.stdout.readline()
        if not line:
            code = self.proc.wait()
            raise Fail(f"Chatterbox stopped unexpectedly (exit code {code}); the lines above say why")
        return json.loads(line)

    def ask(self, **req):
        try:
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
        except OSError:
            pass                                   # it died: reply() reports how
        r = self.reply()
        if "error" in r:
            raise Fail(f"your own voice: {r['error']}")
        return r

    def load(self, voice):
        if voice != self.loaded:
            self.ask(cmd="load", voice=voice, dir=str(own_voices()[voice]))
            self.loaded = voice

    def say(self, voice, text):
        import numpy as np
        import soundfile as sf
        self.load(voice)
        out = self.tmp / "say.wav"
        self.ask(cmd="say", text=text, seed=text_seed(voice, text), out=str(out))
        audio, sr = sf.read(str(out), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        return trim_edges(np.ascontiguousarray(audio, dtype=np.float32))

    def close(self):
        try:
            self.proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
            self.proc.stdin.close()
            self.proc.wait(timeout=30)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.proc.kill()
        if self.proc.stdout:
            self.proc.stdout.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------- assembly

def frame_align(seconds):
    """Round up to a whole number of video frames, so audio and video agree exactly."""
    return math.ceil(round(seconds * FPS, 6)) / FPS


def silence(seconds):
    import numpy as np
    return np.zeros(int(round(seconds * SAMPLE_RATE)), dtype=np.float32)


def segments_for(s, steps, audio_of, args):
    """One slide -> [(state, audio or None, seconds)], every duration frame-aligned.

    Narrated: state 0 opens with the lead-in pad; each later state opens with
    a short beat (the click) before its words; the last state carries the
    trailing pad. Unnarrated build states get --build-hold. A slide with no
    notes plays its builds through at --build-hold each and rests on the
    final state for --empty-duration.
    """
    import numpy as np
    if not s["parts"]:
        n = len(steps)
        return [(k, None, frame_align(args.build_hold if k < n - 1 else args.empty_duration)) for k in range(n)]
    segs = []
    for k, step in enumerate(steps):
        pieces = [silence(args.pad if k == 0 else TURN_GAP)] if (k == 0 or step["parts"]) else []
        for i, part in enumerate(step["parts"]):
            if i:
                pieces.append(silence(TURN_GAP if part["voice"] != step["parts"][i - 1]["voice"] else CHUNK_GAP))
            pieces.append(audio_of[id(part)])
        speech = sum(len(p) for p in pieces) / SAMPLE_RATE
        if not step["parts"] and k > 0:
            speech = args.build_hold        # a build with nothing said over it: [click][click], or spare builds
        if k == len(steps) - 1:
            speech += args.pad
        audio = np.concatenate(pieces) if pieces else None
        segs.append((k, audio, frame_align(speech)))
    return segs


def ffconcat_path(path):
    """Quote a path for an ffconcat file: forward slashes (fine on Windows too),
    and ' escaped the way the concat demuxer expects."""
    return "'" + Path(path).resolve().as_posix().replace("'", "'\\''") + "'"


def assemble(segments, tmp, out_path):
    """segments: list of (png_path, audio ndarray, duration_seconds)."""
    import numpy as np
    import soundfile as sf
    ffmpeg = find_ffmpeg()

    # One continuous audio track, built sample-exact from per-segment durations.
    total = sum(d for _, _, d in segments)
    track = np.zeros(int(round(total * SAMPLE_RATE)), dtype=np.float32)
    concat = ["ffconcat version 1.0"]
    t = 0.0
    for png, audio, dur in segments:
        start = int(round(t * SAMPLE_RATE))
        if audio is not None:
            seg = audio[:int(round(dur * SAMPLE_RATE))]
            track[start:start + len(seg)] = seg[:len(track) - start]
        concat += [f"file {ffconcat_path(png)}", f"duration {dur:.6f}"]
        t += dur
    concat.append(f"file {ffconcat_path(segments[-1][0])}")   # concat demuxer needs the last file repeated
    wav = tmp / "narration.wav"
    sf.write(wav, track, SAMPLE_RATE, subtype="PCM_16")
    (tmp / "slides.ffconcat").write_text("\n".join(concat) + "\n", encoding="utf-8")   # ffmpeg reads UTF-8

    log("Measuring loudness...")
    r = run([ffmpeg, "-hide_banner", "-nostats", "-i", str(wav),
             "-af", f"loudnorm={LOUDNORM}:print_format=json", "-f", "null", "-"], "loudness measurement")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        raise Fail("couldn't parse ffmpeg loudnorm measurement")
    meas = json.loads(m.group(0))
    if meas["input_i"] in ("-inf", "inf"):
        af = "anull"   # all-silent deck: nothing to normalize
    else:
        af = (f"loudnorm={LOUDNORM}:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}"
              f":measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}"
              f":offset={meas['target_offset']}:linear=true")

    log(f"Encoding {out_path.name} ({total:.2f}s, {len(segments)} frames on screen)...")
    vf = (f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,fps={FPS},format=yuv420p")
    part = out_path.with_name(out_path.stem + ".partial.mp4")
    run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", str(tmp / "slides.ffconcat"),
         "-i", str(wav),
         "-map", "0:v", "-map", "1:a",
         "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-tune", "stillimage",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-af", af, "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
         "-t", f"{total:.6f}", "-movflags", "+faststart", str(part)],
        "ffmpeg encode")
    part.replace(out_path)
    return total


# ---------------------------------------------------------------- main

def resolve_output(deck_path, output):
    if output:
        out = Path(output).expanduser()
        if out.is_dir() or output.endswith(("/", os.sep)):
            out = out / (deck_path.stem + ".mp4")
    else:
        out = deck_path.with_suffix(".mp4")
    out = out.resolve()
    # Off by default: a narrated video lands next to its deck, and a deck on the
    # desktop would litter it. Opt in with DECK_NARRATOR_ALLOW_DESKTOP=1.
    if any(p.lower() == "desktop" for p in out.parts[:-1]) and os.environ.get("DECK_NARRATOR_ALLOW_DESKTOP") != "1":
        raise Fail(f"refusing to write to a Desktop folder: {out}. Pass -o somewhere else, "
                   "or set DECK_NARRATOR_ALLOW_DESKTOP=1.")
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------- pronunciation check

G2PS = {}


def g2p_for(lang):
    """Kokoro's phonemizer for a language, without loading the voice model (fast, offline).
    Returns (g2p, fallback_hits): fallback_hits collects the words misaki didn't know and
    handed to espeak, since the last time the caller cleared it."""
    if lang not in G2PS:
        import warnings
        warnings.filterwarnings("ignore")
        from kokoro import KPipeline
        try:
            g2p = KPipeline(lang_code=lang, repo_id=REPO_ID, model=False).g2p
        except ModuleNotFoundError as e:
            raise Fail(f"{LANG_NAMES[lang]} needs an extra package that isn't installed: {e}")
        hits = []
        if getattr(g2p, "fallback", None) is not None:
            real = g2p.fallback

            def fallback(tk, real=real, hits=hits):
                hits.append(tk.text)
                return real(tk)
            g2p.fallback = fallback
        G2PS[lang] = (g2p, hits)
    return G2PS[lang]


def phonemize(voice, text):
    """What Kokoro will say for text with this voice's language, in its phoneme alphabet.
    Your own voices read text, not phonemes, so for them it's the text they'll read."""
    check_voice_name(voice, "--voice")
    if is_own_voice(voice):
        return f"(reads the words) {plain_text(text)}"
    return g2p_for(voice[0])[0](text)[0]


# The lexicon's part-of-speech keys that pick between pronunciations, and what to call them.
POS_LABELS = {"DEFAULT": "usual", "NOUN": "noun", "VERB": "verb", "ADJ": "adjective", "ADV": "adverb",
              "VBD": "past tense", "VBN": "past participle", "VBP": "present tense"}
WORDLIKE = re.compile(r"[A-Za-z][A-Za-z'’.-]*")
SENTENCE = re.compile(r"(?<=[.!?…])\s+")
# Common words with two pronunciations that the lexicon lists only one way (American).
EXTRA_HETERONYMS = {
    "lead": [("lˈid", "to guide"), ("lˈɛd", "the metal")],
    "row": [("ɹˈO", "a line; to paddle"), ("ɹˈW", "an argument")],
    "polish": [("pˈɑlɪʃ", "to shine"), ("pˈOlɪʃ", "from Poland")],
    "address": [("ədɹˈɛs", "verb; British noun"), ("ˈædɹɛs", "noun (American)")],
    "resume": [("ɹəzˈum", "to continue"), ("ɹˈɛzəmˌA", "a CV")],
    "sewer": [("sˈuəɹ", "drain"), ("sˈOəɹ", "someone who sews")],
}


def heteronym_options(g2p, word):
    """[(phonemes, label)] when the lexicon has more than one pronunciation for word, else []."""
    if word.lower() in EXTRA_HETERONYMS and not getattr(g2p.lexicon, "british", False):
        return list(EXTRA_HETERONYMS[word.lower()])
    lex = g2p.lexicon
    entry = None
    for w in (word, word.lower(), word.capitalize()):
        entry = lex.golds.get(w) or lex.silvers.get(w)
        if entry is not None:
            break
    if not isinstance(entry, dict):
        return []
    by_ps = {}
    for tag, ps in entry.items():
        if ps and tag in POS_LABELS:
            by_ps.setdefault(ps, []).append(POS_LABELS[tag])
    if len(by_ps) < 2:
        return []
    return [(ps, " / ".join([l for l in labels if l != "present tense"][:2] or labels[:1]))
            for ps, labels in by_ps.items()]


def nth_word_span(text, word, n):
    """(start, end) of the n-th (1-based) whole-word, case-insensitive occurrence of word
    in text, not counting ones inside other square-bracket stage directions. None if absent."""
    hidden = [m.span() for m in BRACKETED.finditer(text)]
    k = 0
    for m in re.finditer(rf"(?<![\w'’]){re.escape(word)}(?![\w'’])", text, re.I):
        if any(a <= m.start() < b for a, b in hidden):
            continue
        k += 1
        if k == n:
            return m.span()
    return None


def with_override(text, word, n, phonemes):
    """text with the n-th occurrence of word (see nth_word_span) as [word](/phonemes/)."""
    span = nth_word_span(text, word, n)
    if span is None:
        return None
    a, b = span
    if text[b:b + 2] == "](" and text[:a].endswith("["):           # already an override: replace it
        end = text.index(")", b) + 1
        return text[:a - 1] + f"[{text[a:b]}](/{phonemes}/)" + text[end:]
    return text[:a] + f"[{text[a:b]}](/{phonemes}/)" + text[b:]


def pronunciation_issues(slides):
    """Words in the slides' scripts that may come out wrong: heteronyms (one spelling, more
    than one pronunciation, picked from the sentence's grammar), words the lexicon doesn't
    know (guessed by espeak), and all-capitals words that are spelled out letter by letter.
    Words already fixed with [word](/phonemes/) are left out. Each issue says where it is
    (slide, word, n = which occurrence of the word in that slide's notes) so fix_word can
    change exactly that one."""
    issues = []
    for s in slides:
        counts = {}
        for part in s["parts"]:
            # Your own voices read plain text; American English is the closest guide to them.
            g2p, hits = g2p_for(part["voice"][0] if is_kokoro_name(part["voice"]) else "a")
            for sentence in [x for x in SENTENCE.split(part["text"]) if x.strip()]:
                hits.clear()
                _, tokens = g2p(sentence)
                unknown = {h.lower() for h in hits}
                in_sentence = {}
                for tk in tokens:
                    word = tk.text
                    if not WORDLIKE.fullmatch(word):
                        continue
                    key = word.lower()
                    counts[key] = counts.get(key, 0) + 1
                    in_sentence[key] = in_sentence.get(key, 0) + 1
                    if tk._.rating == 5:                    # an override: already decided
                        continue
                    options = heteronym_options(g2p, word)
                    if options:
                        kind = "heteronym"
                    elif key in unknown:
                        kind, options = "unknown", [(tk.phonemes, "best guess")]
                    elif (word.isupper() and len(word) > 3 and re.search("[AEIOUY]", word)
                          and tk.phonemes and tk.phonemes.count("ˌ") >= len(word) - 1):
                        # an all-capitals word that could be said as a word (OPSWAT, NIST), spelled
                        # out instead; short or vowel-less ones (GPU, HTTP) are meant to be spelled
                        kind, options = "spelled", [(tk.phonemes, "spelled out")]
                    else:
                        continue
                    if tk.phonemes and all(ps != tk.phonemes for ps, _ in options):
                        options.insert(0, (tk.phonemes, "what it says now"))
                    issues.append({
                        "slide": s["number"], "word": word, "n": counts[key], "n_in_sentence": in_sentence[key],
                        "kind": kind,
                        "voice": part["voice"], "sentence": sentence, "current": tk.phonemes or "",
                        "options": [{"phonemes": ps, "label": label,
                                     "say": with_override(sentence, word, in_sentence[key], ps)}
                                    for ps, label in options],
                    })
    return issues


def print_issues(issues):
    kinds = {"heteronym": "can be said more than one way", "unknown": "not in the dictionary; guessed",
             "spelled": "all capitals, so it's spelled out letter by letter"}
    if not issues:
        print("No likely pronunciation problems found.")
        return
    for i in issues:
        print(f"slide {i['slide']}: {i['word']!r} ({kinds[i['kind']]}), now /{i['current']}/")
        print(f"    {i['sentence']}")
        for o in i["options"]:
            print(f"    /{o['phonemes']}/  {o['label']}")
    print(f"\n{len(issues)} word(s) to check. Fix one with [word](/phonemes/) in the notes, "
          "or --fix-word SLIDE WORD N PHONEMES.")


def set_paragraph_text(para, old, new):
    """Change a notes paragraph from old to new text, touching only the runs the change
    falls in, so the rest keeps its formatting."""
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    q = 0
    while q < min(len(old), len(new)) - p and old[-1 - q] == new[-1 - q]:
        q += 1
    lo, hi = p, len(old) - q                     # the changed stretch of old
    spans, pos = [], 0
    for r in para.runs:
        spans.append((r, pos, pos + len(r.text)))
        pos += len(r.text)
    hit = ([x for x in spans if x[1] < hi and x[2] > lo]                  # runs the change overlaps
           or [x for x in spans if x[1] <= lo <= x[2]][:1] or spans[-1:])  # a pure insertion: its run
    (r0, start, _), end = hit[0], hit[-1][2]
    r0.text = new[start:end + len(new) - len(old)]
    for r, _, _ in hit[1:]:
        r.text = ""


def fix_word(deck_path, slide_no, word, n, phonemes):
    """Make the n-th occurrence of word in slide slide_no's speaker notes [word](/phonemes/),
    saving the deck in place. The first time, the original is kept as
    '<deck> (before deck-narrator).pptx' next to it."""
    from pptx import Presentation
    phonemes = phonemes.strip().strip("/")
    if not phonemes or "/" in phonemes or ")" in phonemes:
        raise Fail(f"--fix-word: {phonemes!r} isn't a usable phoneme string")
    prs = Presentation(str(deck_path))
    if not 1 <= slide_no <= len(prs.slides):
        raise Fail(f"--fix-word: the deck has no slide {slide_no}")
    slide = prs.slides[slide_no - 1]
    tf = slide.notes_slide.notes_text_frame if slide.has_notes_slide else None
    if tf is None:
        raise Fail(f"--fix-word: slide {slide_no} has no speaker notes")
    seen = 0
    for para in tf.paragraphs:
        text = "".join(r.text for r in para.runs)
        here = 0
        while nth_word_span(text, word, here + 1):
            here += 1
        if seen + here < n:
            seen += here
            continue
        new = with_override(text, word, n - seen, phonemes)
        set_paragraph_text(para, text, new)
        break
    else:
        raise Fail(f"--fix-word: slide {slide_no}'s notes have only {seen} {word!r}, not {n}")
    backup = deck_path.with_name(f"{deck_path.stem} (before deck-narrator){deck_path.suffix}")
    if not backup.exists():
        shutil.copy2(deck_path, backup)
    tmp = deck_path.with_name(deck_path.name + ".tmp")
    prs.save(str(tmp))
    os.replace(tmp, deck_path)
    log(f"Slide {slide_no}: {word} #{n} -> [{word}](/{phonemes}/)" + (f"; original kept as {backup.name}" if backup.exists() else ""))
    return 0


# ---------------------------------------------------------------- voice samples

DEFAULT_SAMPLE_TEXT = "Hello! This is how your deck will sound."


def sample_cache_dirs():
    """Where finished --sample WAVs are kept: samples/ next to the program (pre-recorded,
    shipped with the Windows builds), then a per-user cache. DECK_NARRATOR_SAMPLE_CACHE
    replaces the per-user one."""
    env = os.environ.get("DECK_NARRATOR_SAMPLE_CACHE")
    if env:
        user = Path(env)
    elif os.name == "nt":
        user = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "deck-narrator" / "samples"
    else:
        user = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "deck-narrator" / "samples"
    return [app_dir() / "samples", user]


def sample_key(voice, text, speed):
    """Changes whenever the sound would: the voice, the text after the pronunciation file,
    the speed, and the model. A voice --update-voices replaced adds its file's hash, so the
    pre-recorded samples of the old one aren't used for it."""
    import hashlib
    updated = user_voice_dir() / f"{voice}.pt"
    voice_id = sha256_file(updated) if updated.is_file() else voice
    if is_own_voice(voice):                 # what makes it sound the way it does: its files
        voice_id = [CHATTERBOX] + [[p.name, sha256_file(p) if p.stat().st_size < 50_000_000 else p.stat().st_size,
                                    int(p.stat().st_mtime)] for p in sorted(own_voices()[voice].iterdir()) if p.is_file()]
    blob = json.dumps([REPO_ID, voice, voice_id, round(float(speed), 3), text], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


SAMPLE_CACHE_MAX = 200     # newest kept in the per-user cache


def speak_sample(args):
    """--sample: one phrase to a WAV, for trying voices, speeds and pronunciations."""
    import soundfile as sf
    out = Path(args.output).expanduser() if args.output else Path(tempfile.gettempdir()) / "deck-narrator-sample.wav"
    if out.suffix.lower() != ".wav":
        raise Fail(f"--sample writes a WAV file; give -o a .wav path, not {out.name}")
    if args.speed <= 0:
        raise Fail("--speed must be > 0")
    _, rules = rules_for(args)
    text = apply_pronunciations(clean_notes(args.sample), rules)
    if not text:
        raise Fail("--sample text is empty")
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    name = sample_key(args.voice, text, args.speed) + ".wav"
    dirs = sample_cache_dirs()
    for d in dirs:
        if (d / name).is_file():
            shutil.copyfile(d / name, out)
            try:
                os.utime(d / name)                  # recently used: keep it in the cache
            except OSError:
                pass
            log(f"Sample: {args.voice}, from the saved copy")
            print(out)
            return 0
    tts = TTS(resolve_device(args.device))
    try:
        audio = tts.synthesize(args.voice, text, args.speed)
    finally:
        tts.close()
    sf.write(out, audio, SAMPLE_RATE, subtype="PCM_16")
    log(f"Sample: {len(audio) / SAMPLE_RATE:.2f}s of {args.voice}")
    try:                                            # keep it for next time
        cache = dirs[-1]
        cache.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, cache / (name + ".part"))
        os.replace(cache / (name + ".part"), cache / name)
        for old in sorted(cache.glob("*.wav"), key=lambda f: f.stat().st_mtime)[:-SAMPLE_CACHE_MAX]:
            old.unlink()
    except OSError:
        pass
    print(out)
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.install_own_voice:
        return install_own_voice()
    if args.add_voice:
        return add_voice(*args.add_voice)
    if args.remove_voice:
        return remove_voice(args.remove_voice)
    if args.list_voices:
        list_voices()
        return 0
    if args.update_voices:
        return update_voices()
    check_voice_name(args.voice, "--voice")
    if args.phonemes:
        print(phonemize(args.voice, args.phonemes))
        return 0
    if args.add_word:
        return add_word(args.pronunciations or default_dictionary(), *args.add_word)
    if args.sample:
        return speak_sample(args)
    if not args.deck:
        raise Fail("no deck given. Usage: deck-narrator path/to/deck.pptx")
    deck_path = Path(args.deck).expanduser().resolve()
    if not deck_path.is_file():
        raise Fail(f"no such file: {deck_path}")
    if deck_path.suffix.lower() != ".pptx":
        raise Fail(f"expected a .pptx file, got {deck_path.name}")
    if args.pad < 0 or args.empty_duration <= 0 or args.speed <= 0 or args.build_hold <= 0:
        raise Fail("--pad must be >= 0; --empty-duration, --build-hold and --speed must be > 0")
    if args.fix_word:
        slide_no, word, n, phonemes = args.fix_word
        if not (slide_no.isdigit() and n.isdigit() and int(n) > 0):
            raise Fail("--fix-word SLIDE WORD N PHONEMES: SLIDE and N are numbers, e.g. --fix-word 3 read 1 ɹˈɛd")
        return fix_word(deck_path, int(slide_no), word, int(n), phonemes)
    report_only = args.show_builds or args.show_phonemes or args.check_pronunciation
    out_path = None if report_only else resolve_output(deck_path, args.output)
    dictionary, rules = rules_for(args)
    if dictionary and not args.pronunciations:
        log(f"Dictionary: {dictionary} ({len(rules) - len(BUILTIN_PRONUNCIATIONS)} words)")

    # Fail fast on missing binaries before any slow work.
    if not report_only:
        find_ffmpeg()
        renderer = choose_renderer(args.renderer)

    started = time.time()
    slides = read_deck(deck_path, with_builds=not args.no_builds)
    if not slides:
        raise Fail("the deck has no slides")
    check_overrides([s for s in slides if not s["hidden"]])
    script_deck(slides, args.voice, rules)
    visible = [s for s in slides if not s["hidden"]]
    hidden = len(slides) - len(visible)
    if not any(s["text"] for s in visible):
        raise Fail("no speaker notes found on any visible slide, so there is nothing to narrate. "
                   "Add notes in PowerPoint (View > Notes) and try again.")
    if args.slides:
        visible = [s for s in visible if s["number"] in args.slides]
        if not visible:
            raise Fail(f"--slides selected no visible slides (deck has {len(slides)} slides, {hidden} hidden)")
    if args.skip_empty:
        visible = [s for s in visible if s["text"]]
        if not visible:
            raise Fail("every selected slide is empty and --skip-empty is set; nothing to render")

    with_notes = sum(1 for s in visible if s["text"])
    animated = sum(1 for s in visible if s["builds"].clicks)
    voices = sorted({p["voice"] for s in visible for p in s["parts"]})
    log(f"Deck: {deck_path.name}: {len(slides)} slides, {hidden} hidden, {len(visible)} selected "
        f"({with_notes} with notes, {animated} with builds; voices: {', '.join(voices) or 'none'})")

    plans = {}
    for s in visible:
        plans[s["number"]] = plan_slide(s, args.build_hold)
        for w in plans[s["number"]][1]:
            log(f"  note: slide {s['number']}: {w}")
        if s["builds"].ignored:
            log(f"  note: slide {s['number']}: {'/'.join(sorted(s['builds'].ignored))} effects don't change "
                "a still frame and are skipped")

    if args.show_builds:
        for s in visible:
            b = s["builds"]
            print(f"--- slide {s['number']}: {b.clicks} build click(s) in the deck, {s['clicks']} [click] in the notes")
            for line in s["describe"]():
                print(line)
            for step in plans[s["number"]][0]:
                for part in step["parts"]:
                    print(f"    state {step['state']} says ({part['voice']}): {part['text'][:70]}"
                          f"{'...' if len(part['text']) > 70 else ''}")
            print()
        return 0

    if args.check_pronunciation:
        issues = pronunciation_issues(visible)
        if args.json:
            print(json.dumps({"issues": issues}, ensure_ascii=False))
        else:
            print_issues(issues)
        return 0

    if args.show_phonemes:
        for s in visible:
            if s["parts"]:
                print(f"--- slide {s['number']}")
                for part in s["parts"]:
                    click = f"after click {part['step']}, " if part["step"] else ""
                    print(f"[{click}{part['voice']}] {phonemize(part['voice'], part['text'])}")
                print()
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="deck-narrator-"))
    tts = None
    try:
        pngs = render_states(deck_path, tmp, slides, visible, renderer)
        audio_of = {}
        if with_notes:
            tts = TTS(resolve_device(args.device))
            for v in voices:                    # every voice loads before any long work
                first = next(s["number"] for s in visible for p in s["parts"] if p["voice"] == v)
                tts.pipe(v, f"slide {first}")
            for i, s in enumerate(visible, 1):
                if not s["parts"]:
                    continue
                t0 = time.time()
                for part in s["parts"]:
                    audio_of[id(part)] = tts.synthesize(part["voice"], part["text"], args.speed)
                speech = sum(len(audio_of[id(p)]) for p in s["parts"]) / SAMPLE_RATE
                extra = f", {s['builds'].clicks} builds" if s["builds"].clicks else ""
                who = sorted({p["voice"] for p in s["parts"]})
                log(f"[{i}/{len(visible)}] slide {s['number']}: {speech:.2f}s narration "
                    f"({len(s['text'])} chars{extra}{', voices ' + '+'.join(who) if len(voices) > 1 else ''}, "
                    f"{time.time() - t0:.1f}s to synthesize)")
            tts.close()
            gains = level_voices([(p["voice"], audio_of[id(p)]) for s in visible for p in s["parts"]])
            if gains:
                log("Voice levels matched: " + ", ".join(f"{v} x{g:.2f}" for v, g in sorted(gains.items())))

        segments, manifest = [], []
        for s in visible:
            steps, warnings = plans[s["number"]]
            segs = segments_for(s, steps, audio_of, args)
            for state, audio, dur in segs:
                segments.append((pngs[(s["number"], state)], audio, dur))
            if not s["parts"]:
                log(f"slide {s['number']}: no notes, {sum(d for _, _, d in segs):.2f}s silent")
            manifest.append({
                "slide": s["number"],
                "build_states": len(steps),
                "clicks_in_notes": s["clicks"],
                "parts": [{"step": p["step"], "voice": p["voice"], "spoken_text": p["text"],
                           "seconds": round(len(audio_of[id(p)]) / SAMPLE_RATE, 6)} for p in s["parts"]],
                "segments": [{"state": st, "seconds": round(d, 6)} for st, _, d in segs],
                "slide_seconds": round(sum(d for _, _, d in segs), 6),
                "warnings": warnings,
            })
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        total = assemble(segments, tmp, out_path)
        log(f"Done: {out_path} ({total:.2f}s) in {time.time() - started:.0f}s")
        print(out_path)
    finally:
        if tts is not None:
            tts.close()
        if args.keep_temp:
            log(f"Kept intermediate files in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as e:
        log(f"deck-narrator: error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("deck-narrator: interrupted")
        sys.exit(130)
