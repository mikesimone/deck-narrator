# Using Deck Narrator

How to use the app once it's installed: the window, writing speaker notes the voice reads
well, slide animations, more than one voice, and what error messages mean. To install it, go
back to the [README](../README.md). Pronunciation has its own page:
[Fixing pronunciation](PRONUNCIATION.md).

## Contents

- [The GUI](#the-gui)
- [Writing notes for narration](#writing-notes-for-narration)
- [Animation builds](#animation-builds)
- [Switching voices](#switching-voices)
- [Voices](#voices)
- [Errors and what they mean](#errors-and-what-they-mean)
- [Known limits](#known-limits)

## The GUI

**Deck Narrator** in the Start menu (Windows installer) or in Applications (Mac), `deck-narrator-gui.exe` (zip),
`deck-narrator-gui.cmd` (Windows from source) or `deck-narrator-gui` (Linux, after
`setup.sh`) opens a window with every option the command line has:

- **Deck** tab: the deck, where to save the video (blank = next to the deck), and which
  slides (blank = all).
- **Voice** tab: pick a voice and speed, type something and press **Play sample** to hear
  it.
- **Pronunciation** tab: **Phonemes for** shows how any word or phrase will be said, and
  **Show every slide's phonemes** does the whole deck. It also shows which
  [dictionary](PRONUNCIATION.md#the-pronunciation-file-every-occurrence) is in use and how
  many words it has; **Edit** opens it in Notepad (or your editor).
- **Settings** (top right) holds what rarely changes: the pauses, skipping empty slides,
  ignoring animations, keeping temp files, saving to a Desktop folder, which dictionary
  file to use (**Import...**, **New...**, **Edit**, or **Use my own**), PowerPoint or
  LibreOffice for drawing slides, CPU or GPU, and the startup checks for new voices and for
  Deck Narrator updates (each with **Check now**), and a **Buy me a coffee** tip-jar link.
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
  dictionary, so every deck says it that way from now on, and every other place it's
  listed (any slide, any capitalization) is ticked off too. Your dictionary is
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
  - `[word](/phonemes/)` fixes a pronunciation ([docs/PRONUNCIATION.md](PRONUNCIATION.md)).
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
  [PRONUNCIATION.md](PRONUNCIATION.md#british-voices).

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
