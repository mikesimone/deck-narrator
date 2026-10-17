# Reference

The command line and the technical details: every option, what happens inside a run,
the output format, what gets installed where, and how it's tested. For everyday use,
see [Using Deck Narrator](GUIDE.md).

## Contents

- [Run it](#run-it)
- [Every option](#every-option)
- [What it does, step by step](#what-it-does-step-by-step)
- [Output format and timing](#output-format-and-timing)
- [What gets installed](#what-gets-installed)
- [GPU or CPU](#gpu-or-cpu)
- [Your own voice](#your-own-voice)
- [Testing](#testing)
- [Files in this repo](#files-in-this-repo)
- [Privacy](#privacy)

## Run it

```bash
deck-narrator ~/path/to/deck.pptx
```

On Windows: `deck-narrator C:\path\to\deck.pptx` (or `deck-narrator.exe` in the standalone
folder).

That writes `~/path/to/deck.mp4` next to the deck and prints its path as the last line.
Progress goes to stderr, one line per slide. Here's a five-slide deck with builds
and three voices:

```
Deck: deck.pptx: 5 slides, 0 hidden, 5 selected (4 with notes, 3 with builds; voices: af_heart, am_michael, bf_emma)
  note: slide 2: slide has 3 build step(s) but the notes have 2 [click]; the last 1 play after the narration, 1s each
  note: slide 2: emph effects don't change a still frame and are skipped
Rendering build pass 1/4 with LibreOffice...
Rendering build pass 2/4 with LibreOffice...
Rendering build pass 3/4 with LibreOffice...
Rendering build pass 4/4 with LibreOffice...
Loading Kokoro-82M on cuda...
[1/5] slide 1: 8.25s narration (105 chars, 3 builds, voices af_heart, 0.5s to synthesize)
[2/5] slide 2: 9.12s narration (110 chars, 3 builds, voices af_heart, 0.1s to synthesize)
[3/5] slide 3: 14.57s narration (201 chars, voices af_heart+am_michael+bf_emma, 0.2s to synthesize)
[4/5] slide 4: 3.92s narration (55 chars, voices am_michael, 0.0s to synthesize)
Voice levels matched: af_heart x1.00, am_michael x1.15, bf_emma x0.77
slide 5: no notes, 5.00s silent
Measuring loudness...
Encoding deck.mp4 (51.17s, 13 frames on screen)...
Done: /home/you/decks/deck.mp4 (51.17s) in 11s
```

A typical loop for a new deck:

```bash
deck-narrator deck.pptx --show-builds                      # 1. do the [click]s line up with the animations?
deck-narrator deck.pptx --show-phonemes                    # 2. read what it will say, and who says it
deck-narrator deck.pptx --slides 1-2                       # 3. listen to a short preview
deck-narrator deck.pptx --pronunciations deck.words.txt    # 4. the full render
```

Steps 1 and 2 take seconds and render nothing.

## Every option

| Option | Default | What it does |
|---|---|---|
| `deck` | (required) | Path to the `.pptx` |
| `-o`, `--output PATH` | next to the deck | Output `.mp4` path, or a directory to write `<deck name>.mp4` into (end it with `/`, or it must already exist). Parent directories are created if needed |
| `--slides SPEC` | all | Only these slides, in PowerPoint numbering (hidden slides count toward the numbering): `3-5`, `1,4,6-8` |
| `--voice NAME` | `af_heart` | Starting voice, see [Voices](GUIDE.md#voices). `[voice: name]` in the notes switches it |
| `--list-voices` | | Print the available voices and exit |
| `--speed X` | `1.0` | Speech rate multiplier. `1.1` is 10% faster |
| `--pad SECONDS` | `0.75` | Silence before **and** after each slide's narration |
| `--empty-duration SECONDS` | `3.0` | How long a slide with no notes is shown |
| `--skip-empty` | off | Drop slides with no notes instead of showing them |
| `--show-builds` | | Print each selected slide's build states, what changes at each click, and which text is spoken over which state, and exit. No video |
| `--no-builds` | off | Ignore animations: every slide fully built, `[click]` ignored |
| `--build-hold SECONDS` | `1.0` | How long a build state shows when nothing is said over it |
| `--pronunciations FILE` | your dictionary | `word=replacement` list applied before speech, see [PRONUNCIATION.md](PRONUNCIATION.md#the-pronunciation-file-every-occurrence). Without it, your personal dictionary is used if you have one (the log says so) |
| `--add-word WORD PHONEMES` | | Save `WORD=[WORD](/PHONEMES/)` in the dictionary (`--pronunciations FILE`, else your personal dictionary, created the first time), so `WORD` is said that way in every deck, and exit. A rule for the same word is replaced in place. The GUI's **Use this** does this for new words |
| `--show-phonemes` | | Print every selected slide's script as phonemes, one line per voice and click, after stage directions and the pronunciation file, and exit. No video. Combine with `--slides`, `--pronunciations` and `--voice` |
| `--phonemes TEXT` | | Print the phonemes for `TEXT` and exit. Doesn't need a deck |
| `--check-pronunciation` | | List the words in the selected slides' notes that may be said wrong (more than one pronunciation, not in the dictionary, or an all-capitals word spelled out), with each word's sentence and choices, and exit. No video. `--json` prints it as JSON (the GUI uses that) |
| `--fix-word SLIDE WORD N PHONEMES` | | Write `[WORD](/PHONEMES/)` in place of the `N`th `WORD` in slide `SLIDE`'s notes and save the deck. The first time, the original is kept as `<deck> (before deck-narrator).pptx`. `N` counts every whole-word `WORD` in that slide's notes, fixed or not, case ignored |
| `--sample TEXT` | | Speak `TEXT` into a WAV with `--voice`, `--speed` and `--pronunciations`, print its path and exit. `-o` names the `.wav` (default: `deck-narrator-sample.wav` in the temp folder). Doesn't need a deck. The GUI's **Play sample** uses this. Samples are saved (see [The GUI](GUIDE.md#the-gui)), so the same one again is instant |
| `--device auto\|cuda\|mps\|cpu` | `auto` | Where the voices run. `auto` uses CUDA when torch can see an NVIDIA GPU, the Mac's GPU (`mps`) on Apple Silicon, else the CPU. Kokoro and your own voice each decide with their own PyTorch: the Windows installer and zip carry a CPU-only one for Kokoro (quick enough), while your own voice's setup gets the NVIDIA build when there's a card, so `auto` puts it on the GPU |
| `--renderer auto\|powerpoint\|keynote\|libreoffice` | `auto` | What draws the slides. `auto` uses Microsoft PowerPoint when it's installed (Windows), Keynote on a Mac, else LibreOffice |
| `--install-own-voice` | | Set up Chatterbox for [your own voice](OWN-VOICE.md) (4 to 6 GB, once; run again to repair), print `own-voice: ready`, and exit |
| `--add-voice NAME FILE` | | Make your own voice `NAME` from `FILE`: a 10-30 second recording (`.wav`, `.flac`, `.mp3`, `.ogg`) or a [voice pack](OWN-VOICE.md#voice-packs) (`.zip` or folder). Replaces a voice of the same name. Prints `voice: NAME` and exits |
| `--remove-voice NAME` | | Delete your own voice `NAME` and exit |
| `--remove-own-voice-support` | | Delete Chatterbox, its Python and its model (4 to 6 GB) and exit. Your voices in `my-voices` are kept; `--install-own-voice` brings it back |
| `--update-voices` | | Download voices that are new or updated on HuggingFace since the install, into a per-user folder, print one `voices: ...` line, and exit. Only for installs with bundled voices; others download voices on use anyway |
| `--keep-temp` | off | Keep the temp dir (PNGs, PDF, WAV, `manifest.json`) and print its path |
| `--version` | | Print the version and exit |
| `-h`, `--help` | | Usage |

Environment variables are listed under [What gets installed](#what-gets-installed).

## What it does, step by step

1. **Read the deck** (python-pptx). For each slide: is it hidden (`show="0"`), what are its
   speaker notes, and what are its animation build states (`builds.py`, from the slide's
   `<p:timing>` main sequence).
2. **Turn the notes into a script.** Any `[word] (/.../)` with a stray space stops the run.
   `[click]` and `[voice: ...]` markers split the notes into parts, each with a build step
   and a voice. The voice carries from slide to slide. Other stage directions are stripped,
   whitespace is collapsed, and the pronunciation file is applied. Parts that land on the
   same build state with the same voice are joined, so they're voiced in one go.
3. **Render the slides.** With PowerPoint (Windows, when it's installed), PowerPoint opens
   each deck copy read-only and windowless and exports exactly the slides each pass needs
   as 1920px PNGs; it's quit afterwards only if it wasn't already running. Otherwise,
   headless LibreOffice exports the deck to PDF **with hidden slides
   included** (`ExportHiddenSlides=true`), so PDF page N is always slide N, then checks that
   the page count matches. With animations, there's one more export per click on the
   busiest slide, from edited copies of the deck (see [Animation builds](GUIDE.md#animation-builds)).
   Every export's page count is checked against the slides it should contain. pypdfium2
   (PDFium, the PDF engine in Chrome) rasterizes each page at 1920px on the long side. LibreOffice runs with a throwaway profile
   in the temp dir, so it works even if LibreOffice is open elsewhere, and never touches a
   real profile.
4. **Generate the narration** (Kokoro-82M via the `kokoro` package; misaki + spaCy for
   phonemes; espeak-ng, bundled with misaki, for unknown words). Every voice the script uses is loaded first, so
   a bad name fails before any long work. Each part is split at sentence ends into chunks of
   up to 350 characters, and the chunks are voiced and joined. With more than one voice,
   each voice is then scaled to a common speech level.
5. **Assemble** (ffmpeg). The tool builds one continuous audio track sample by sample, with
   each build state's narration placed in its segment. The video is a concat list of the
   build-state PNGs, each held for its segment's exact duration, letterboxed to 1920x1080. Two-pass
   `loudnorm` normalizes the audio, and everything is encoded in one ffmpeg run. It writes
   to `<name>.partial.mp4` first and renames on success, so a failed run never leaves a
   half-written file under the real name.
6. **Clean up.** The temp dir (`/tmp/deck-narrator-*`) is deleted unless you passed `--keep-temp`.

`--keep-temp` leaves `manifest.json` in the temp dir. For each slide it records the build
states, the `[click]` count, every part (step, voice, the exact text spoken, seconds), each
on-screen segment, and any warnings. It's the first thing to check when something sounds or
looks off.

## Output format and timing

| | |
|---|---|
| Container | MP4, `+faststart` (starts playing before the download finishes) |
| Video | H.264 High, 1920x1080, 30 fps, yuv420p, CRF 18, `-tune stillimage` |
| Audio | AAC 192 kb/s, 48 kHz, two-pass loudnorm to **-16 LUFS** integrated, -1.5 dBTP |
| Plays on | Anything: phones, browsers, Slack, PowerPoint, TVs |

**Slide timing:** a narrated slide without builds is on screen for `pad + narration + pad`.
With builds, it's split into one segment per build state:

| Segment | Length |
|---|---|
| State 0 | `pad` + what's said before the first `[click]` |
| Each later state with words | 0.35s beat + its words |
| A state with nothing said over it | `--build-hold` |
| The last state | its own length + `pad` |
| Within a state | 0.2s between one voice's sentences, 0.35s at a change of voice |

Every segment is rounded **up** to a whole frame (1/30 s), so audio and video stay exactly in
step; the rounding adds less than 1/30 s per segment. Slides without notes get
`--empty-duration` (after their builds, if any). The total video length is the sum of the
segments; the test suite checks that against an independent calculation with ffprobe.

Non-16:9 decks (4:3, say) are letterboxed with black bars, never stretched.

## What gets installed

| What | Linux (`setup.sh`) | Windows (`setup.ps1`) | Why |
|---|---|---|---|
| LibreOffice | apt `libreoffice-impress` | winget `TheDocumentFoundation.LibreOffice` | Slide rendering |
| ffmpeg | apt `ffmpeg` | winget `Gyan.FFmpeg` | Encoding and loudness |
| tkinter | apt `python3-tk` | (included with Python) | The GUI. Only needed if the venv uses the system Python |
| Fonts | apt `fonts-dejavu`, `fonts-liberation`, `fonts-crosextra-carlito`, `fonts-crosextra-caladea` | (Windows has its own) | Metric-compatible stand-ins for Calibri, Cambria, Arial and Times, so text wraps as it does in PowerPoint |
| Microsoft core fonts | `--ms-fonts`: apt `ttf-mscorefonts-installer`, accepting its EULA | (built in) | Real Georgia, Arial, Verdana and Times. Without them a Georgia title, for example, falls back to DejaVu Serif |
| [uv](https://docs.astral.sh/uv/) | if missing | if missing | Creates the venv and installs Python packages |
| `.venv/` (Python 3.12, gitignored) | yes | yes | torch first, from PyTorch's index: the CUDA 12.8 build if `nvidia-smi` works (RTX 50-series cards need cu128 or newer), else the CPU build. Then `requirements.txt`: kokoro, misaki, python-pptx, pypdfium2, soundfile, numpy, `en_core_web_sm` |
| On PATH | `~/.local/bin/deck-narrator` symlink | `-AddToPath`: this folder on your user PATH | So `deck-narrator` works from anywhere |
| Kokoro-82M model + default voice | `~/.cache/huggingface` | `%USERPROFILE%\.cache\huggingface` | Pre-fetched so the first run doesn't stall |

The wrappers (`deck-narrator` on Linux, `deck-narrator.cmd` on Windows, and the
`deck-narrator-gui` pair) just run `narrate.py` or `gui.py` with the venv's Python, so
nothing needs activating.

**The Windows installer** puts everything in `Program Files\Deck Narrator`: the two
programs, their bundled Python and libraries, and `model\` with Kokoro-82M and every voice.
It adds a Start menu entry and the folder to the system PATH, and nothing else (no desktop
icon). ffmpeg is included, in `ffmpeg\` (a GPL-3.0 build from gyan.dev). LibreOffice
isn't; see [Install](WINDOWS.md#drawing-the-slides-powerpoint-or-libreoffice) for the minimal, Office-safe install it offers.

Voices that appear on HuggingFace after the install (or updated versions of included ones)
go into a per-user folder, `%LOCALAPPDATA%\deck-narrator\voices`
(`~/.local/share/deck-narrator/voices` on Linux), and win over the bundled copies.

Environment variables, all optional:

| Variable | Effect |
|---|---|
| `DECK_NARRATOR_SOFFICE` | Full path to LibreOffice's `soffice` (`soffice.com` on Windows), if it isn't found automatically |
| `DECK_NARRATOR_FFMPEG` | Full path to `ffmpeg`. Otherwise the bundled `ffmpeg\ffmpeg.exe` (Windows builds), else PATH |
| `DECK_NARRATOR_RENDERER` | `powerpoint`, `keynote` or `libreoffice`, overriding `--renderer` |
| `DECK_NARRATOR_VOICE_DIR` | Where `--update-voices` puts new and updated voices (default: the per-user folder above) |
| `DECK_NARRATOR_SAMPLE_CACHE` | Where finished samples are saved (default: `%LOCALAPPDATA%\deck-narrator\samples`, or `~/.cache/deck-narrator/samples`) |
| `DECK_NARRATOR_DICTIONARY` | Where your personal pronunciation dictionary is (default: `%APPDATA%\deck-narrator\pronunciations.txt`, or `~/.config/deck-narrator/pronunciations.txt`) |
| `DECK_NARRATOR_THEME` | `light` or `dark` for the GUI, instead of following Windows |
| `DECK_NARRATOR_ALLOW_DESKTOP=1` | Allow writing into a Desktop folder |
| `DECK_NARRATOR_OWN_VOICE_HOME` | Where Chatterbox's Python, model and installer go (default: `chatterbox` in the per-user data folder, `%LOCALAPPDATA%\deck-narrator` or `~/.local/share/deck-narrator`) |
| `DECK_NARRATOR_MY_VOICES` | Where your own voices go (default: `my-voices` in the same data folder) |
| `DECK_NARRATOR_TORCH_BACKEND` | Which PyTorch `--install-own-voice` installs (`cpu`, `cu128`, ...), instead of CUDA 12.8 when `nvidia-smi` finds a GPU, else CPU |
| `DECK_NARRATOR_MODEL_DIR` | A folder holding `config.json`, `kokoro-v1_0.pth` and `voices/*.pt`, used instead of downloading. Without it, a `model/` folder next to the program is used if there is one (the Windows installer puts one there); otherwise the HuggingFace download and cache. `packaging/fetch_model.py DEST` makes such a folder |

If a deck uses a font that isn't installed, LibreOffice substitutes another one without
warning. On Linux, check with `fc-match "Font Name"`, and install the font into
`~/.local/share/fonts/`, then run `fc-cache -f`. On Windows, install it the usual way.

## GPU or CPU

`--device auto` (the default) uses an NVIDIA GPU when PyTorch can see one, and the CPU
otherwise. Kokoro is small (82M parameters), so the CPU is perfectly usable: a 3:43 deck
took about 40 seconds on an 8-core desktop CPU, against about 25 on an RTX 5060 Ti. Most
of the time goes to LibreOffice and encoding either way.

On the GPU it uses about **0.7 GB of VRAM**, only while a run is going, and releases it
when the process exits. If the GPU is busy with something more important, `--device cpu`
leaves it alone.

The Windows standalone zip is a CPU build, so it works on any machine; install from source
for GPU speed.

## Your own voice

Optional, and set up separately (see [OWN-VOICE.md](OWN-VOICE.md) for the everyday side).
Chatterbox needs a different PyTorch and transformers from Kokoro's, so it gets its own
Python rather than sharing deck-narrator's:

- `--install-own-voice` downloads [uv](https://github.com/astral-sh/uv) (a pinned release
  from PyPI, checked against its SHA-256), which installs Python 3.11 and a virtual
  environment with `chatterbox-tts` 0.1.7 and PyTorch 2.8 (CUDA 12.8 when `nvidia-smi` finds
  an NVIDIA GPU, else CPU; the standard build on a Mac), then downloads Chatterbox's model
  from HuggingFace (`ResembleAI/chatterbox`) into that folder, plus faster-whisper and its
  `base.en` model (about 200 MB, for the cut-off check below). It asks for 10 GB free first.
  `ready.json` in that folder records the versions and whether its PyTorch sees an NVIDIA
  or Apple GPU (Settings shows it). Nothing goes into deck-narrator's own install. A setup
  made by 1.3.0 gets faster-whisper added on its first use.
- A voice is a folder in `my-voices`: `reference.*`, plus `t3.safetensors`, `voice.json`
  and `timbre_reference.*` when it came from a voice pack. Names are `[a-z0-9][a-z0-9_-]{0,31}`, and can't look like
  a Kokoro name (`af_...`) or be `default`.
- During a run, `own_voice_worker.py` runs in that Python (offline, `HF_HUB_OFFLINE=1`) and
  speaks each chunk of notes on request (one JSON line each way). `--device` goes to it as
  given and its own PyTorch resolves it. Notes are spoken in chunks of up to 200 characters
  (Kokoro's are 350), with a progress line and a time estimate for each.
- Each chunk is seeded from the voice and the text, so it comes out the same every time.
  Three of Chatterbox's silence tokens go before the vocoder (as Chatterbox Turbo does), so
  the last sound isn't clipped. faster-whisper (`base.en`, on the CPU) then transcribes the
  clip; if the last word or much of the text is missing, it's spoken again with the next
  seed, up to 3 tries, keeping the best. Retries are logged and are just as repeatable.
- A voice pack's `pause_scale` lengthens each pause of at least 0.12 s inside a clip (by
  repeating its own quiet audio, at most 0.35 s added), and `speed` time-stretches the clip
  with ffmpeg's `atempo`, keeping the pitch. Sentences of your own voice are 0.35 s apart
  (Kokoro's chunks, 0.2 s).
- Clips are trimmed, faded in and out (10 ms), and the gaps between them get a quiet room
  tone at the clips' own background level (clamped to -70 to -45 dBFS) instead of digital
  silence, so the joins don't sound like the audio switching off.
- Phoneme overrides are read as the plain word, and `--speed` is ignored for these voices
  (the log says so). `--show-phonemes` and `--phonemes` show the words instead.
- It's much heavier than Kokoro: about 3 to 5 GB of VRAM on an NVIDIA GPU, and slow on a CPU.

## Testing

```bash
test/verify.sh                                   # Linux
.\.venv\Scripts\python.exe test\verify.py        # Windows
```

Extra arguments go to deck-narrator (`--device cpu`, for one). `verify.py --exe PATH` runs
the same suite against a packaged build instead of the source. CI
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) runs it on Linux and on Windows, from
source, then builds the Windows standalone zip and runs the suite again against the built
`.exe`. Then it builds the MSI, installs it, runs the suite and the GUI against the installed
copy with HuggingFace switched off (so everything must come from the installer), checks
`--update-voices` both offline and online, saves
screenshots of the GUI, and uninstalls it, checking that the files, Start menu entry and
PATH entry are gone. On Linux it also opens the GUI on a virtual display.

1. **Unit tests** (84, no GPU, a few seconds). On their own:
   `.venv/bin/python -m unittest discover -s test -v`
   - `test/test_text.py`: stage-direction stripping, keeping overrides, the
     detached-override check, pronunciation-file rules (whole word, case, longest first,
     single pass, overrides win, bad lines), sentence splitting (bounded chunks, no words
     lost, overrides never split), and `--slides` parsing.
   - `test/test_builds.py`: animation parsing (paragraph builds, with/after previous,
     auto-start, exits, emphasis, enter-then-exit), state rendering (shape removal, hidden
     paragraphs keep their text, missing targets reported), the `[click]`/`[voice: ...]`
     script (steps, switching, `default`, carry-over, bad names, punctuation after a
     marker, overrides aren't markers), folding, and click-count mismatch warnings.
   - `test/test_gui.py`: every command-line option has a GUI control (a new option fails
     this until the GUI has it), and every button builds a command line that parses to
     the intended options.
   - `test/test_model_dir.py`: finding a bundled model, falling back to downloading, and
     `--update-voices` (new and changed voices, offline, nothing bundled), with HuggingFace mocked.
   - `test/test_tools.py`: choosing PowerPoint or LibreOffice, the bundled ffmpeg, and the
     PowerPoint build passes exporting the right slides.
   - `test/test_pronunciation.py`: what `--check-pronunciation` finds (and leaves alone),
     `--fix-word` (the right occurrence, formatting kept, the backup, bad requests), and the
     sample cache (cached, pre-recorded first, and the key changing with what you'd hear).
2. **End to end, two decks**, each rendered and checked by `test/check_video.py`:
   - `test/test-deck.pptx` (`make_test_deck.py`): multi-sentence notes with stage
     directions, an inline override, a hidden slide, a slide with no notes, and a long
     paragraph ending in "pineapple" as a truncation canary.
   - `test/anim-deck.pptx` (`make_anim_deck.py`): bullets built by paragraph; shapes with
     an auto-start entrance, two shapes on one click (with previous), an exit, an
     emphasis-only click, and fewer `[click]`s than builds; a three-voice conversation;
     a voice carried to the next slide; and an animated slide with no notes. Its animation
     XML is written the way PowerPoint writes it.

   The checks: H.264 + AAC present at 1920x1080 yuv420p; the expected slides and build-state
   counts; each slide's duration against an independent formula, within one frame per
   segment; container, video and audio durations against the total; a frame grabbed
   mid-segment matches **that** build state better than any other state of the slide; and
   the voice of every part.
3. **Pronunciation and samples**, through the same program: `--check-pronunciation --json`
   on the test deck, `--fix-word` on a copy (the fixed word must drop off the list, and the
   backup must exist), and the same `--sample` twice (the second must come from the saved
   copy). Ends `ALL: PASS` or `ALL: FAIL`.

The frame check was itself tested: swapping two build states in a kept run's frame list
makes it fail. The animated deck was also round-tripped through LibreOffice's own PPTX
writer (pptx to odp to pptx), which rewrites the animation XML with different ids and
structure. It parsed to the same build states and rendered the same frames.

The test outputs (`test/*-deck.pptx`, `test/*-deck.mp4`) are gitignored.

## Files in this repo

| File | What |
|---|---|
| `narrate.py` | The tool. Read top to bottom: notes and script, timing, rendering, TTS, assembly, `main` |
| `builds.py` | Animation builds: parsing `<p:timing>`, rendering a build state, `--show-builds` text |
| `deck-narrator` | Linux wrapper that runs `narrate.py` with `.venv/bin/python` (symlinked onto PATH) |
| `deck-narrator.cmd` | Windows wrapper, same job |
| `gui.py` | The GUI (tkinter): builds the command line from the form and runs it |
| `deck-narrator-gui`, `deck-narrator-gui.cmd` | GUI wrappers for Linux and Windows |
| `setup.sh`, `setup.ps1` | Install everything, on Linux and Windows |
| `requirements.txt` | Python deps (torch is installed separately, from PyTorch's index) |
| `packaging/` | The PyInstaller spec (both programs), the icon and logo (`make_art.py` draws them and the installer images, in the brand colors), `fetch_model.py` (bundles the voices), `prerender_samples.py` (records the default sample in every English voice), `install-dependencies.ps1`/`.cmd` (the minimal LibreOffice install), what goes in the zip besides the programs, `installer/` (the WiX source, license page and banner images for the MSI), and `winget/`, `chocolatey/` and `publish-packages.ps1` (the winget and Chocolatey packages, built and submitted after each release) |
| `.github/workflows/ci.yml` | Tests on Linux, macOS and Windows, builds the zip, the MSI and the Mac `.dmg`, tests the installed MSI and the Mac app, attaches them to releases |
| `LICENSE`, `THIRD-PARTY-NOTICES.md` | MIT for this code; what the zip and installer bundle and under which licenses |
| `docs/` | The guides: `WINDOWS.md`, `MAC.md` and `LINUX.md` (installing), `GUIDE.md` (using it), `PRONUNCIATION.md`, `AI-NOTES.md` (having an AI write the notes), this `REFERENCE.md`, and `release-notes/` |
| `test/verify.py` (`verify.sh`) | Unit tests plus both end-to-end checks |
| `test/test_text.py`, `test/test_builds.py`, `test/test_gui.py`, `test/test_model_dir.py`, `test/test_tools.py`, `test/test_pronunciation.py`, `test/test_own_voice.py` | Unit tests |
| `own_voice_worker.py` | Speaks in your own voice with Chatterbox, in Chatterbox's own Python (see [Your own voice](#your-own-voice)) |
| `test/own_voice_check.py` | End-to-end check of your own voice with the real Chatterbox (CI runs it on Linux and with the Windows `.exe`) |
| `test/gui_selftest.ps1` | Drives the GUI on Windows and screenshots it (CI runs it against the installed MSI) |
| `test/check_video.py` | The end-to-end checks on a rendered video |
| `test/make_test_deck.py` | Builds the narration test deck |
| `test/make_anim_deck.py` | Builds the animation/voices test deck (and a PowerPoint-format timing writer the unit tests reuse) |
| `test/pronunciations.txt` | Example pronunciation file |
| `examples/demo-deck.pptx` | A small deck to try: builds, `[click]`s and three voices (a copy of the test suite's `anim-deck.pptx`) |
| `examples/how-to/` | A how-to deck about the app itself (1.2.5): many screenshots revealed by builds, and notes in deck-narrator syntax whose narration demonstrates each sound; run it through deck-narrator for a narrated tour. `deck-narrator-how-to-1.2.5.mp4` is that video (linked at the top of the README) |

## Privacy

deck-narrator collects no data and sends nothing about you or your decks
anywhere; decks, notes and videos never leave your computer. It connects to the internet
only for these, and nothing else:

- **HuggingFace** (huggingface.co), to download the Kokoro voice model and voices, and,
  when **Check for new voices** is on (the GUI's default, at most once a day) or
  `--update-voices` is run, to list the voices available. Turn the check off in
  **Settings**.
- **GitHub** (api.github.com and github.com), at most once a day while **Check for Deck
  Narrator updates** is on (the default), to see whether there's a newer release, and to
  download it when you press **Update**. Turn the check off in **Settings**.
- **PyPI, PyTorch and HuggingFace** (files.pythonhosted.org, pypi.org,
  download.pytorch.org, huggingface.co, and the Python builds uv fetches from
  github.com), only when you set up [your own voice](OWN-VOICE.md), to download uv,
  Python, Chatterbox and its model. Your recordings and voices never leave your computer.
- **The Document Foundation** (download.documentfoundation.org), only when you run
  `install-dependencies.cmd` (or press **Install LibreOffice**, or tick the installer's
  checkbox) on a PC without PowerPoint or LibreOffice, to download LibreOffice.

The **Buy me a coffee** button in **Settings** opens ko-fi.com in your browser, only when
you click it.

Those services' own privacy policies apply to those downloads.
