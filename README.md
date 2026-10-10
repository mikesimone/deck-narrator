# deck-narrator

Turns a PowerPoint deck with speaker notes into a voice-narrated MP4. No recording,
no paid services, no API keys. The voice is
[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), running locally on the GPU,
or on the CPU if there isn't one.

- **Runs on Linux and Windows.** Windows has an installer (MSI) on the
  [Releases](../../releases) page that includes the voices, a standalone zip, or a native
  PowerShell install from source. See [Install](#install).
- **A window or a command line.** The [GUI](#the-gui) can do everything the command line can.
- **Speed:** a 20-slide, 3:43 deck renders in about 25 seconds on an NVIDIA RTX 5060 Ti, or
  about 40 seconds on an 8-core desktop CPU (Ryzen 7 9700X) with no GPU at all.
- **Animation builds:** bullets and shapes appear on screen as the narration reaches each
  `[click]` in the notes. See [Animation builds](#animation-builds).
- **More than one voice:** `[voice: am_michael]` in the notes switches narrator. See
  [Switching voices](#switching-voices).
- **Mispronounced word?** See [docs/PRONUNCIATION.md](docs/PRONUNCIATION.md), or the
  [short version](#pronunciation-the-short-version) below.

## Contents

- [Install](#install)
- [Run it](#run-it)
- [The GUI](#the-gui)
- [Writing notes for narration](#writing-notes-for-narration)
- [Animation builds](#animation-builds)
- [Switching voices](#switching-voices)
- [Pronunciation, the short version](#pronunciation-the-short-version)
- [Every option](#every-option)
- [What it does, step by step](#what-it-does-step-by-step)
- [Output format and timing](#output-format-and-timing)
- [Voices](#voices)
- [Errors and what they mean](#errors-and-what-they-mean)
- [What gets installed](#what-gets-installed)
- [GPU or CPU](#gpu-or-cpu)
- [Testing](#testing)
- [Files in this repo](#files-in-this-repo)
- [Known limits](#known-limits)
- [Code signing policy and privacy](#code-signing-policy-and-privacy)

## Install

**Windows, installer (simplest).** Download `deck-narrator-<version>-x64.msi` from the
[Releases](../../releases) page and run it. It installs to `Program Files\Deck Narrator` for
all users, adds **Deck Narrator** to the Start menu, and puts `deck-narrator.exe` on the
system PATH. The voice model, all its voices and ffmpeg are included (the MSI is large
because of them), so nothing is downloaded when you first make a video. Uninstall from
Settings > Apps.

**Drawing the slides** takes Microsoft PowerPoint or LibreOffice. If PowerPoint is installed,
Deck Narrator uses it and nothing else is needed. If not, leave **Install LibreOffice if
it's needed** ticked on the installer's last page (or press **Install LibreOffice** in the
GUI, or run `install-dependencies.cmd` in the install folder). It downloads LibreOffice
straight from The Document Foundation (no winget needed), checks the download's signature,
and installs only what Deck Narrator uses, leaving Office alone:

- `REGISTER_NO_MSO_TYPES=1`: LibreOffice doesn't take over `.pptx`, `.docx` or `.xlsx`, so
  they keep opening in Office.
- No Base, Math or online updater, and no desktop icon. (Writer and Calc stay, because
  Impress's PDF export crashes without them.)

A silent install that does the same: `msiexec /i deck-narrator-<version>-x64.msi /qn INSTALLDEPS=1`.

Code signing for the Windows releases is being set up with the
[SignPath Foundation](https://signpath.org) (free code signing for open-source projects;
see [Code signing policy](#code-signing-policy-and-privacy)). Until then, Windows may warn
that the installer is from an unknown publisher, because it isn't code-signed. Choose **More info**, then **Run anyway**.

**Windows, standalone zip.** `deck-narrator-windows-x64.zip` on the same page is the same
program without an installer: unzip it anywhere and run `deck-narrator-gui.exe` or
`deck-narrator.exe`. It includes ffmpeg and `install-dependencies.cmd`, and downloads the
voice model (about 330 MB) the first time it speaks.

Both run the voice on the CPU; for NVIDIA GPU speed, install from source.

**Windows, from source** (native PowerShell; no WSL, no Docker; uses the GPU if there is one):

```powershell
git clone https://github.com/mikesimone/deck-narrator.git
cd deck-narrator
.\setup.ps1 -AddToPath
```

`setup.ps1` installs LibreOffice and ffmpeg with winget if they're missing, installs
[uv](https://docs.astral.sh/uv/) if it's missing, and creates `.venv` with everything else.
`-AddToPath` puts the folder on your user PATH so `deck-narrator` works from any folder (in a
new terminal); without it, run `.\deck-narrator.cmd`. The GUI is `.\deck-narrator-gui.cmd`.

**Linux (Debian/Ubuntu):**

```bash
git clone https://github.com/mikesimone/deck-narrator.git ~/deck-narrator
~/deck-narrator/setup.sh             # add --ms-fonts for Microsoft's core fonts, see below
```

`setup.sh` installs LibreOffice, ffmpeg and fonts with apt, installs uv if it's missing,
creates `.venv`, and links `~/.local/bin/deck-narrator`. On other distributions, install
LibreOffice (Impress) and ffmpeg with your package manager and run the rest of `setup.sh`
by hand. It's short.

Both setup scripts can be re-run safely, and both pre-download the voice model (about
330 MB) so the first real run doesn't stall. Details: [What gets installed](#what-gets-installed).

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

## The GUI

**Deck Narrator** in the Start menu (installer), `deck-narrator-gui.exe` (zip),
`deck-narrator-gui.cmd` (Windows from source) or `deck-narrator-gui` (Linux, after
`setup.sh`) opens a window with every option the command line has:

- **Deck** tab: the deck, where to save the video (blank = next to the deck), and which
  slides (blank = all).
- **Voice** tab: pick a voice and speed, type something and press **Play sample** to hear
  it.
- **Pronunciation** tab: **Phonemes for** shows how any word or phrase will be said, and
  **Show every slide's phonemes** does the whole deck. It also shows which
  [dictionary](docs/PRONUNCIATION.md#the-pronunciation-file-every-occurrence) is in use and how
  many words it has; **Edit** opens it in Notepad (or your editor).
- **Settings** (top right) holds what rarely changes: the pauses, skipping empty slides,
  ignoring animations, keeping temp files, saving to a Desktop folder, which dictionary
  file to use (**Import...**, **New...**, **Edit**, or **Use my own**), PowerPoint or
  LibreOffice for drawing slides, CPU or GPU, and the startup checks for new voices and for
  Deck Narrator updates (each with **Check now**).
- **Log** tab: the full output of the last run. It comes forward when something runs.
- **Make video**, **Check builds** (the `--show-builds` report) and **Check pronunciation**
  (see below) sit under the tabs, with the progress bar; **Cancel** stops a
  run. When a video is done, **Play video** and **Open folder** open it.

**Check pronunciation** lists only the words that may come out wrong: words with more than
one pronunciation (read, record, present, lead...), words that aren't in the voice's
dictionary (so it guesses), and all-capitals names it would spell out letter by letter
(OPSWAT). Pick one to see its sentence and each way of saying it, each with **Play**. What
**Use this** does depends on the word:

- **A word the voice doesn't know, or spells out:** it's saved in your pronunciation
  dictionary, so every deck says it that way from now on. Your dictionary is
  `%APPDATA%\deck-narrator\pronunciations.txt` (Linux: `~/.config/deck-narrator/pronunciations.txt`).
  The first word saved creates it, and from then on it's used automatically, by the window
  and the command line alike. To use a different file, pick it in **Settings**.
- **A word with more than one pronunciation** (read, present): the right one depends on
  the sentence, so the choice is written into that slide's speaker notes as
  `[word](/phonemes/)` and the deck is saved. The first time, the original is kept next to
  it as `<deck> (before deck-narrator).pptx`. Close the deck in PowerPoint first, or it
  can't be saved.

If none of the choices is right, type a spelling that
sounds right (`op swat`) under **Sounds like**, then **Play** or **Use this**. (The full phoneme listing of every slide is on the
**Pronunciation** tab.)

**Play sample** is instant for the default sentence in every English voice: the Windows
builds come with those recorded. Any other sample is saved after it's made the first time
(the newest 200 are kept), so playing it again is instant too.

**Updates:** with **Check for Deck Narrator updates at startup** on (in **Settings**;
on by default), it asks GitHub once a day for the latest release. When there's a newer one,
an **Update to x.y.z** button appears at the top. In the installed copy it downloads the
new installer, checks it against the SHA-256 checksum GitHub lists for it, closes, installs
it over the old version (the installer always replaces the previous one) and opens again.
The zip and source copies open the download page instead.

The window fits a 1024x768 screen. It follows Windows' light or dark app setting
(`DECK_NARRATOR_THEME=light` or `dark` overrides it).

The GUI is a front end: each button runs the command-line program with the matching
options (the log's first line shows the exact command), so the two always behave the
same. Your choices are remembered between runs (`%APPDATA%\deck-narrator\gui.json` on
Windows, `~/.config/deck-narrator/gui.json` on Linux).

**To try it:** open `examples/demo-deck.pptx`, a five-slide deck whose notes use animation
builds and three voices (it's the deck the tests use), and press **Make video**.

**Desktop folders:** like the command line, it won't save a video into a Desktop folder
unless you tick **Allow saving to a Desktop folder**.

## Writing notes for narration

The speaker notes are the script, word for word. What helps:

- **Punctuation is pacing.** A comma is a short pause, a period a longer one. `[pause]`
  is not a pause; see the next point.
- **Three kinds of square brackets do something:**
  - `[click]` advances the slide's animation builds ([Animation builds](#animation-builds)).
    On a slide with no animations it does nothing at all.
  - `[voice: name]` switches narrator ([Switching voices](#switching-voices)).
  - `[word](/phonemes/)` fixes a pronunciation ([docs/PRONUNCIATION.md](docs/PRONUNCIATION.md)).
- **Every other stage direction is removed.** `[pause]`, `[Slide 3]`, `[laughs]` and the like are
  stripped from the spoken text, so notes you already wrote for live presenting still work.
  Markers are case-insensitive: `[Click]` and `[VOICE: am_michael]` work too.
- **Spell out anything that should be said a particular way:** "version two point oh"
  rather than "v2.0". Key combos are already handled: `Alt+Shift+M` is read "Alt plus
  Shift plus M".
- **A slide with no notes** is shown silently for 3 seconds (`--empty-duration`), or dropped
  entirely with `--skip-empty`.
- **Hidden slides** are skipped: not shown, not spoken.
- **Long notes are fine.** Notes are split at sentence boundaries into chunks of up to
  350 characters, each chunk is voiced separately, and the chunks are joined with a
  0.2s gap. Nothing is truncated; the unit tests check that no words are lost.

## Animation builds

If a slide builds (bullets that appear one per click, a picture that flies in, a box that
disappears), the video shows each build state in turn, switching at the `[click]` markers in
your notes:

```
Here's the problem. [click] First, tabs pile up. [click] Second, they all look alike.
```

```
state 0  title only          "Here's the problem."
state 1  + first bullet      "First, tabs pile up."
state 2  + second bullet     "Second, they all look alike."
```

The picture changes, there's a 0.35s beat, then the words start, just like a presenter
clicking and then talking. Each state stays up exactly as long as its words take.

**Check the match before rendering:**

```
$ deck-narrator deck.pptx --show-builds --slides 2
--- slide 2: 3 build click(s) in the deck, 2 [click] in the notes
  state 0 (start): hidden at start: Rectangle 4, Rectangle 5
  state 1 (click 1): shows Rectangle 4, Rectangle 5
  state 2 (click 2): hides Rectangle 3
  state 3 (click 3): no visible change (emphasis or motion only)
    state 0 says (af_heart): Box A starts on screen, and the subtitle fades in by itself.
    state 1 says (af_heart): Boxes B and C arrive together.
    state 2 says (af_heart): Now box A is gone.
```

Shape names are the ones in PowerPoint's Selection Pane (Home > Arrange > Selection Pane),
and `¶2` means the shape's second paragraph.

**What counts as a click.** The tool follows PowerPoint's own sequence:

| In PowerPoint | In the video |
|---|---|
| **On Click** | A new build state, reached at the next `[click]` |
| **With Previous** / **After Previous** following a click | Part of that click's state: everything lands together |
| **With/After Previous** as the very first animation | Already on screen when the slide opens (state 0) |
| **Entrance** effects (Appear, Fade, Fly In, Wipe, ...) | The shape or paragraph appears |
| **Exit** effects | It disappears |
| **Emphasis** (Pulse, Spin, Grow, color changes...) | Nothing changes, but it still counts as a click, so your `[click]` count matches PowerPoint's |
| **Motion paths** | Nothing moves (shapes stay where they are drawn). Still counts as a click |
| Bullets **By Paragraph** | One paragraph per click. Hidden bullets keep their space, so nothing on the slide shifts as later ones appear |

**When the counts don't match**, the tool still renders and prints a note:

| Notes vs. slide | What happens |
|---|---|
| Same number of `[click]`s as builds | Each block of text gets its own state |
| **Fewer** `[click]`s than builds | The leftover builds play after the narration, `--build-hold` seconds each (default 1s) |
| **More** `[click]`s than builds | Text after the last build's click stays on the final state |
| `[click]` on a slide with no animations | Ignored completely; the text is voiced in one go |
| `[click][click]` with nothing in between | That state shows for `--build-hold` seconds, with nothing said over it |
| Animated slide with **no notes** | The builds play through, `--build-hold` each, then the final state rests for `--empty-duration` |

`--no-builds` turns all of this off: every slide is shown fully built, as before builds were
supported.

**How it's rendered.** LibreOffice can't export animation steps, so the tool makes them: for
each state it edits a copy of the slide, removing shapes that aren't on screen yet (or anymore)
and making hidden bullets fully transparent with no bullet glyph, so they keep their space. It
then renders that copy like any other slide. It does this in passes. Pass *k* renders
state *k* of every slide that has one, so a deck costs one LibreOffice export per click on its
busiest slide, plus one: a deck whose busiest slide has 3 clicks takes 4 exports, however many
other slides animate. A deck with no animations takes exactly one, as before.

## Switching voices

Put `[voice: name]` anywhere in the notes. The new voice speaks from there on, **including
on later slides**, until the next marker. `[voice: default]` goes back to the `--voice` you
started with (af_heart unless you passed one).

```
Slide 3 notes:
  Welcome back. [voice: am_michael] Thanks. Let me show you the export flow.
  [voice: bf_emma] And I'll cover sharing. [voice: default] Over to you both.

Slide 4 notes:
  This is still the default voice, since slide 3 ended on it.
```

- **It works across `--slides` too.** The voice is worked out over the whole deck in order,
  so `--slides 4` uses whoever was speaking at the end of slide 3, just as a full render
  would.
- **Hidden slides don't count.** A `[voice: ...]` on a hidden slide is ignored, along with the
  rest of that slide's notes.
- **Turn-taking:** a voice change mid-slide leaves a 0.35s beat between speakers (one voice's
  own sentences are 0.2s apart).
- **Levels are matched.** Kokoro's voices come out at different volumes, so before the final
  loudness pass every voice is scaled to the same speech level and a switch doesn't sound like
  a volume change. The tool prints the gains (`Voice levels matched: af_heart x1.00,
  am_michael x1.15, bf_emma x0.77`).
- **American and British voices can share a deck.** Each language gets its own pronunciation
  front end, and they share one loaded model, so switching costs nothing.
- **A bad name fails before any rendering**, naming the slide: `slide 3: unknown voice 'bob'`.
- `--show-phonemes` labels every line with its voice and click: `[after click 2, am_michael] ...`.
- Overrides (`[word](/phonemes/)`) must use the phonemes of the voice speaking them. British
  voices use a slightly different phoneme set. Look up with that voice:
  `deck-narrator --voice bf_emma --phonemes "..."`. See
  [PRONUNCIATION.md](docs/PRONUNCIATION.md#british-voices).

## Pronunciation, the short version

The voice reads notes through a phonemizer that tags each word's part of speech, so most
heteronyms come out right on their own. ("When you present a presentation sometime in the
present" is read correctly with no help.) When it gets one wrong:

1. **Find it:** `deck-narrator deck.pptx --check-pronunciation` lists just the words that
   may be wrong, with the ways each can be said (the GUI's **Check pronunciation** shows
   the same, with **Play** and **Use this** buttons). `--show-phonemes` prints everything
   each slide will say.
2. **Look up the reading you want:** use a sentence where the word can only be read
   one way, and copy that word's phonemes:
   ```bash
   deck-narrator --phonemes "Let me present it."     # lˈɛt mˌi pɹizˈɛnt ɪt.   (verb)
   deck-narrator --phonemes "I got you a present."   # ˌI ɡɑt ju ɐ pɹˈɛzᵊnt.   (noun)
   ```
3. **Fix that one occurrence in the notes:**
   ```
   ...share your screen or [present](/pɹizˈɛnt/), everyone gets...
   ```
   No space between `]` and `(`; the tool refuses to render if there is one.

For words that are wrong *everywhere* (acronyms, product names), use a pronunciation file:

```
# deck.words.txt: word=replacement, whole word, case-sensitive
NGINX=engine x
NVMe=N V M E
Kubernetes=[Kubernetes](/kˌubəɹnˈɛtiz/)
```

```bash
deck-narrator deck.pptx --pronunciations deck.words.txt
```

[docs/PRONUNCIATION.md](docs/PRONUNCIATION.md) has the rest: the worked "present"
example from a real deck, stress nudges (`[word](-1)`, `[word](+2)`), a
phoneme cheat sheet, a heteronym table, real misreads, and every mistake and what it
does.

## Every option

| Option | Default | What it does |
|---|---|---|
| `deck` | (required) | Path to the `.pptx` |
| `-o`, `--output PATH` | next to the deck | Output `.mp4` path, or a directory to write `<deck name>.mp4` into (end it with `/`, or it must already exist). Parent directories are created if needed |
| `--slides SPEC` | all | Only these slides, in PowerPoint numbering (hidden slides count toward the numbering): `3-5`, `1,4,6-8` |
| `--voice NAME` | `af_heart` | Starting voice, see [Voices](#voices). `[voice: name]` in the notes switches it |
| `--list-voices` | | Print the available voices and exit |
| `--speed X` | `1.0` | Speech rate multiplier. `1.1` is 10% faster |
| `--pad SECONDS` | `0.75` | Silence before **and** after each slide's narration |
| `--empty-duration SECONDS` | `3.0` | How long a slide with no notes is shown |
| `--skip-empty` | off | Drop slides with no notes instead of showing them |
| `--show-builds` | | Print each selected slide's build states, what changes at each click, and which text is spoken over which state, and exit. No video |
| `--no-builds` | off | Ignore animations: every slide fully built, `[click]` ignored |
| `--build-hold SECONDS` | `1.0` | How long a build state shows when nothing is said over it |
| `--pronunciations FILE` | your dictionary | `word=replacement` list applied before speech, see [PRONUNCIATION.md](docs/PRONUNCIATION.md#the-pronunciation-file-every-occurrence). Without it, your personal dictionary is used if you have one (the log says so) |
| `--add-word WORD PHONEMES` | | Save `WORD=[WORD](/PHONEMES/)` in the dictionary (`--pronunciations FILE`, else your personal dictionary, created the first time), so `WORD` is said that way in every deck, and exit. A rule for the same word is replaced in place. The GUI's **Use this** does this for new words |
| `--show-phonemes` | | Print every selected slide's script as phonemes, one line per voice and click, after stage directions and the pronunciation file, and exit. No video. Combine with `--slides`, `--pronunciations` and `--voice` |
| `--phonemes TEXT` | | Print the phonemes for `TEXT` and exit. Doesn't need a deck |
| `--check-pronunciation` | | List the words in the selected slides' notes that may be said wrong (more than one pronunciation, not in the dictionary, or an all-capitals word spelled out), with each word's sentence and choices, and exit. No video. `--json` prints it as JSON (the GUI uses that) |
| `--fix-word SLIDE WORD N PHONEMES` | | Write `[WORD](/PHONEMES/)` in place of the `N`th `WORD` in slide `SLIDE`'s notes and save the deck. The first time, the original is kept as `<deck> (before deck-narrator).pptx`. `N` counts every whole-word `WORD` in that slide's notes, fixed or not, case ignored |
| `--sample TEXT` | | Speak `TEXT` into a WAV with `--voice`, `--speed` and `--pronunciations`, print its path and exit. `-o` names the `.wav` (default: `deck-narrator-sample.wav` in the temp folder). Doesn't need a deck. The GUI's **Play sample** uses this. Samples are saved (see [The GUI](#the-gui)), so the same one again is instant |
| `--device auto\|cuda\|cpu` | `auto` | Where Kokoro runs. `auto` uses CUDA when torch can see a GPU |
| `--renderer auto\|powerpoint\|libreoffice` | `auto` | What draws the slides. `auto` uses Microsoft PowerPoint when it's installed (Windows), else LibreOffice |
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
   busiest slide, from edited copies of the deck (see [Animation builds](#animation-builds)).
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

## Voices

```bash
deck-narrator --list-voices
```

That lists the live set from HuggingFace, or a built-in list if offline. Names are
`<language><gender>_<name>`. The first letter is the language: `a` American English,
`b` British English, others below. The second letter is `f` or `m`.

| Good English choices | |
|---|---|
| `af_heart` (default) | American, female, warm; the top-rated voice in Kokoro's own voice notes |
| `af_bella`, `af_nicole`, `af_sarah` | American, female |
| `am_michael`, `am_adam`, `am_fenrir` | American, male |
| `bf_emma`, `bm_george`, `bm_fable` | British |

Try one on a single slide: `deck-narrator deck.pptx --slides 1 --voice am_michael`. To use
several, see [Switching voices](#switching-voices).
Each voice is a ~0.5 MB download the first time it's used.

Only English voices (`a*`, `b*`) work out of the box. Other languages (`e` Spanish,
`f` French, `h` Hindi, `i` Italian, `j` Japanese, `p` Portuguese, `z` Mandarin) need
extra misaki packages; the tool says so instead of failing obscurely.

## Errors and what they mean

Every error is one line starting `deck-narrator: error:`, with exit code 1, and no traceback.

| Message (abridged) | Meaning / fix |
|---|---|
| `no speaker notes found on any visible slide` | Nothing to narrate. Add notes (PowerPoint: View > Notes) |
| `slide N: pronunciation override '...' has a space between ] and (` | Write `[word](/phonemes/)` with nothing between `]` and `(` |
| `file:LINE: expected word=replacement` | A bad line in the pronunciation file; fix it or comment it out with `#` |
| `--slides selected no visible slides` | The range only covers hidden or nonexistent slides |
| `LibreOffice (soffice) not found` / `ffmpeg not found` | The message says how to install it on your OS (on Windows: `install-dependencies.cmd`; or install PowerPoint). If it's installed somewhere unusual, point at it with `DECK_NARRATOR_SOFFICE` / `DECK_NARRATOR_FFMPEG` (full path to the executable) |
| `--renderer powerpoint: Microsoft PowerPoint isn't installed` | Use `--renderer auto` or `libreoffice` |
| `PowerPoint export failed` | Shows PowerPoint's own error. Usually a corrupt or password-protected deck; `--renderer libreoffice` to try the other renderer |
| `PDF has X pages but Y were expected` | A LibreOffice export (one per build pass) didn't contain exactly the slides asked for, so pages can't be mapped to slides safely. Re-save the deck in PowerPoint and retry; `--no-builds` as a workaround if it only happens with builds |
| `LibreOffice PDF export failed` | Shows LibreOffice's own last lines. Usually a corrupt or password-protected deck |
| `could not load Kokoro model or voice ... from HuggingFace` | First-run download failed (network), or a voice name that doesn't exist (check `--list-voices`) |
| `--voice: unknown voice 'x'` / `slide N: unknown voice 'x'` | Not a valid voice name, in the option or in a `[voice: ...]` marker on slide N; check `--list-voices` |
| `slide N: could not load voice ...` | A well-formed name that doesn't exist (`af_nobody`), or a download failure on first use |
| `voice 'zf_...' needs an extra package` | A non-English voice; see [Voices](#voices) |
| `--device cuda requested but CUDA is not available` | Use `--device auto` or `cpu` |
| `refusing to write to a Desktop folder` | Off by default, so a deck saved on the desktop doesn't scatter videos across it. Pass `-o` somewhere else, or set `DECK_NARRATOR_ALLOW_DESKTOP=1` |
| `could not open ... as a .pptx` | Not a real `.pptx` (an old `.ppt`? Re-save as `.pptx`) |

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
isn't; see [Install](#install) for the minimal, Office-safe install it offers.

Voices that appear on HuggingFace after the install (or updated versions of included ones)
go into a per-user folder, `%LOCALAPPDATA%\deck-narrator\voices`
(`~/.local/share/deck-narrator/voices` on Linux), and win over the bundled copies.

Environment variables, all optional:

| Variable | Effect |
|---|---|
| `DECK_NARRATOR_SOFFICE` | Full path to LibreOffice's `soffice` (`soffice.com` on Windows), if it isn't found automatically |
| `DECK_NARRATOR_FFMPEG` | Full path to `ffmpeg`. Otherwise the bundled `ffmpeg\ffmpeg.exe` (Windows builds), else PATH |
| `DECK_NARRATOR_RENDERER` | `powerpoint` or `libreoffice`, overriding `--renderer` |
| `DECK_NARRATOR_VOICE_DIR` | Where `--update-voices` puts new and updated voices (default: the per-user folder above) |
| `DECK_NARRATOR_SAMPLE_CACHE` | Where finished samples are saved (default: `%LOCALAPPDATA%\deck-narrator\samples`, or `~/.cache/deck-narrator/samples`) |
| `DECK_NARRATOR_DICTIONARY` | Where your personal pronunciation dictionary is (default: `%APPDATA%\deck-narrator\pronunciations.txt`, or `~/.config/deck-narrator/pronunciations.txt`) |
| `DECK_NARRATOR_THEME` | `light` or `dark` for the GUI, instead of following Windows |
| `DECK_NARRATOR_ALLOW_DESKTOP=1` | Allow writing into a Desktop folder |
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

## Testing

```bash
test/verify.sh                                   # Linux
.\.venv\Scripts\python.exe test\verify.py        # Windows
```

Extra arguments go to deck-narrator (`--device cpu`, for one). `verify.py --exe PATH` runs
the same suite against a packaged build instead of the source. CI
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs it on Linux and on Windows, from
source, then builds the Windows standalone zip and runs the suite again against the built
`.exe`. Then it builds the MSI, installs it, runs the suite and the GUI against the installed
copy with HuggingFace switched off (so everything must come from the installer), checks
`--update-voices` both offline and online, saves
screenshots of the GUI, and uninstalls it, checking that the files, Start menu entry and
PATH entry are gone. On Linux it also opens the GUI on a virtual display.

1. **Unit tests** (75, no GPU, a few seconds). On their own:
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
| `packaging/` | The PyInstaller spec (both programs), the icon and logo (`make_art.py` draws them and the installer images, in the brand colors), `fetch_model.py` (bundles the voices), `prerender_samples.py` (records the default sample in every English voice), `install-dependencies.ps1`/`.cmd` (the minimal LibreOffice install), what goes in the zip besides the programs, and `installer/` (the WiX source, license page and banner images for the MSI) |
| `.github/workflows/ci.yml` | Tests on Linux and Windows, builds the zip and the MSI, tests the installed MSI, attaches both to releases |
| `LICENSE`, `THIRD-PARTY-NOTICES.md` | MIT for this code; what the zip and installer bundle and under which licenses |
| `docs/PRONUNCIATION.md` | The full pronunciation guide |
| `test/verify.py` (`verify.sh`) | Unit tests plus both end-to-end checks |
| `test/test_text.py`, `test/test_builds.py`, `test/test_gui.py`, `test/test_model_dir.py`, `test/test_tools.py`, `test/test_pronunciation.py` | Unit tests |
| `test/gui_selftest.ps1` | Drives the GUI on Windows and screenshots it (CI runs it against the installed MSI) |
| `test/check_video.py` | The end-to-end checks on a rendered video |
| `test/make_test_deck.py` | Builds the narration test deck |
| `test/make_anim_deck.py` | Builds the animation/voices test deck (and a PowerPoint-format timing writer the unit tests reuse) |
| `test/pronunciations.txt` | Example pronunciation file |
| `examples/demo-deck.pptx` | A small deck to try: builds, `[click]`s and three voices (a copy of the test suite's `anim-deck.pptx`) |
| `examples/how-to/` | A how-to deck about the app itself (1.2.1): screenshots with builds, notes in deck-narrator syntax, and embedded screen recordings; run it through deck-narrator for a narrated tour |

## Known limits

- **Builds are cuts, not motion.** Each build state is a still; a fly-in or fade becomes a
  cut. Emphasis effects and motion paths aren't shown (they still count as clicks).
- **Character-by-character text builds** are treated as the whole shape appearing at once.
- **Triggered animations** (on click of a specific shape) and **timed auto-advance** are
  ignored; only the main click sequence counts.
- **An exit on an early item of a numbered list renumbers the rest** in that state: with
  item 1 hidden, item 2 shows as "1." (verified in LibreOffice). Numbered items *appearing*
  one by one are unaffected.
- **Video or audio embedded in slides isn't played.**
- **Rendering is LibreOffice's, not PowerPoint's.** It's close, but SmartArt, 3D models
  and some effects can look different. Check a preview.
- **English only** out of the box (see [Voices](#voices)).
- **No `.ppt`** (the pre-2007 format). Re-save as `.pptx`.

## License

MIT for this repository's code (`LICENSE`). The Windows standalone zip bundles third-party
packages, including GPL-3.0 ones, and is distributed under the GPL-3.0 as a whole; see
`THIRD-PARTY-NOTICES.md`. The Kokoro-82M model is Apache-2.0.

## Code signing policy and privacy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org).

Windows releases (the MSI, and the programs in it and in the zip) are built from this
repository by GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)); nothing
is built or signed on a personal machine.

- **Committers and reviewers:** [Mike Simone](https://github.com/mikesimone), the sole maintainer.
- **Approvers:** Mike Simone approves every release before it is signed.
- Only code in this repository and the unmodified third-party components listed in
  [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) are signed.

**Privacy.** deck-narrator collects no data and sends nothing about you or your decks
anywhere; decks, notes and videos never leave your computer. It connects to the internet
only for these, and nothing else:

- **HuggingFace** (huggingface.co), to download the Kokoro voice model and voices, and,
  when **Check for new voices** is on (the GUI's default, at most once a day) or
  `--update-voices` is run, to list the voices available. Turn the check off in
  **Settings**.
- **GitHub** (api.github.com and github.com), at most once a day while **Check for Deck
  Narrator updates** is on (the default), to see whether there's a newer release, and to
  download it when you press **Update**. Turn the check off in **Settings**.
- **The Document Foundation** (download.documentfoundation.org), only when you run
  `install-dependencies.cmd` (or press **Install LibreOffice**, or tick the installer's
  checkbox) on a PC without PowerPoint or LibreOffice, to download LibreOffice.

Those services' own privacy policies apply to those downloads.
