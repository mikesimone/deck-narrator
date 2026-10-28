# Fixing pronunciation

The voice reads your speaker notes. When it says a word wrong, fix it in the notes
or in a pronunciation file. This guide covers both, how to tell what it will say
before rendering, and the mistakes worth avoiding.

**The easy way, before reading any further:**

1. **Have an AI write the notes.** It spells out abbreviations and respells names the voice
   would misread, and it hands you a list of those words for your dictionary.
   [Let an AI write your notes](AI-NOTES.md) has a prompt to copy.
2. **Click Check pronunciation** in Deck Narrator. It lists only the words that may come out
   wrong. Pick one, **Play** each way of saying it, and click **Use this** on the right one.
   If none is right, type a spelling that sounds right (`op swat`) under **Sounds like**.

The rest of this page is for doing it by hand, and for the command line.

Every phoneme string on this page was produced by the tool itself
(`deck-narrator --phonemes ...`), not written by hand.

## Contents

- [How the voice decides how to say a word](#how-the-voice-decides-how-to-say-a-word)
- [The workflow: find it, look it up, fix it](#the-workflow-find-it-look-it-up-fix-it)
- [Worked example: "present" in a real deck](#worked-example-present-in-a-real-deck)
- [Inline overrides: one occurrence](#inline-overrides-one-occurrence)
- [Stress nudges: no phonemes needed](#stress-nudges-no-phonemes-needed)
- [The pronunciation file: every occurrence](#the-pronunciation-file-every-occurrence)
- [Which tool for which job](#which-tool-for-which-job)
- [Phoneme cheat sheet](#phoneme-cheat-sheet)
- [British voices](#british-voices)
- [Common heteronyms](#common-heteronyms)
- [Mistakes and what happens](#mistakes-and-what-happens)
- [Order of operations](#order-of-operations)

## How the voice decides how to say a word

Kokoro doesn't read letters. Its phonemizer, [misaki](https://github.com/hexgrad/misaki),
turns text into phonemes first, and Kokoro voices those. For each word, misaki:

1. Tags its **part of speech** in context with spaCy (`en_core_web_sm`), so it can tell
   "to *present*" (verb) from "a *present*" (noun).
2. Looks the word up in its US English dictionaries. Heteronyms have one entry per part
   of speech.
3. Falls back to espeak-ng for words it has never seen (names, jargon, made-up product
   names). That's where most odd-sounding words come from.

Step 1 is right most of the time. This sentence is handled correctly with no help:

```
When you present a presentation sometime in the present.
wˌɛn ju pɹizˈɛnt ɐ pɹˌɛzᵊntˈAʃən sˈʌmtˌIm ɪn ðə pɹˈɛzᵊnt.
          ^^^^^^^ verb                            ^^^^^^^^ noun
```

The tagger guesses wrong when a sentence is short, ambiguous, or leaves out the
word that would settle it, as in "share your screen or present" below. Abbreviations,
version numbers and brand names also go wrong. Those are what this guide fixes.

## The workflow: find it, look it up, fix it

**1. Find it, without rendering anything.** `--show-phonemes` prints every slide's notes
as phonemes and exits. It takes a couple of seconds, and you can scan it for words that
look wrong:

```bash
deck-narrator deck.pptx --show-phonemes
deck-narrator deck.pptx --show-phonemes --slides 4-6        # just a few slides
deck-narrator deck.pptx --show-phonemes --pronunciations words.txt   # with your file applied
```

Or watch the video and note the slide number. `--slides N` re-renders a single slide
in seconds, so you can check a fix by ear.

**2. Look up the reading you want.** Write a short sentence where the word can only be
read one way, and ask for its phonemes:

```bash
deck-narrator --phonemes "Let me present it."      # lˈɛt mˌi pɹizˈɛnt ɪt.
deck-narrator --phonemes "I got you a present."    # ˌI ɡɑt ju ɐ pɹˈɛzᵊnt.
```

Copy the phonemes for your word: `pɹizˈɛnt` is the verb, `pɹˈɛzᵊnt` the noun.

If no sentence gives the reading you want, look up a word that sounds the same:
`deck-narrator --phonemes "led"` gives `lˈɛd` for the metal "lead". For a made-up
name, look up a respelling: `deck-narrator --phonemes "noo-tanix"` gives `nˈutˈænɪks`.
Or skip phonemes and put the plain respelling in the pronunciation file.

**3. Fix it.** Put the override in the speaker notes (one occurrence) or the
pronunciation file (every occurrence). Then re-check with `--show-phonemes`, or
render that slide with `--slides N`.

## Worked example: "present" in a real deck

One real deck's first slide had this in its speaker notes, and the voice got "present" wrong:

> ...and if you have to share your screen or present, everyone gets a front-row seat...

Here "present" is a verb (to give a presentation). With no object after it, the tagger
read it as a noun:

```
$ deck-narrator --phonemes "if you have to share your screen or present, everyone gets a front-row seat"
ɪf ju hæv tə ʃˈɛɹ jʊɹ skɹˈin ɔɹ pɹˈɛzᵊnt, ˈɛvɹiwən ɡɛts ɐ fɹˈʌntɹˌO sˈit
                                ^^^^^^^^ PREZ-ent (the noun): wrong
```

The fix, typed into slide 1's speaker notes in PowerPoint:

```
...if you have to share your screen or [present](/pɹizˈɛnt/), everyone gets a front-row seat...
```

```
ɪf ju hæv tə ʃˈɛɹ jʊɹ skɹˈin ɔɹ pɹizˈɛnt, ˈɛvɹiwən ɡɛts ɐ fɹˈʌntɹˌO sˈit
                                ^^^^^^^^ pri-ZENT (the verb): right
```

The same deck says "presenters", "presentation" and "presenter window" on slides 5 and 6.
Those are separate dictionary words with only one reading, so they came out right.

## Inline overrides: one occurrence

Syntax, typed straight into the speaker notes:

```
[word](/phonemes/)
```

- `word` is what's being replaced. It's never spoken; only the phonemes are. It can be
  several words: `[New York](/nˌu jˈɔɹk/)`.
- The phonemes go between two slashes, in misaki's alphabet (see the
  [cheat sheet](#phoneme-cheat-sheet)). Copy them from `--phonemes` output; don't
  type IPA from scratch.
- No space between `]` and `(`. If there is one, the tool stops with an error naming
  the slide (see [mistakes](#mistakes-and-what-happens)).
- It affects only that one occurrence. The same word elsewhere is untouched.

This is misaki's own markup, so the tool only has to pass it through untouched. The
`[pause]`/`[click]` stage-direction stripping is written to recognize it: a bracket
followed directly by `(` is an override and is kept; any other bracket is a stage
direction and is removed.

**The markup also shows up in PowerPoint's presenter view.** That doesn't matter
for a narrated video. If you also present the deck live, it's a small cost; keep
overrides to the few words that need them.

## Stress nudges: no phonemes needed

Instead of phonemes, the parentheses can hold a number that shifts the stress the word
already has:

| Markup | Effect | Example (tool output) |
|---|---|---|
| `[word](-1)` | Primary stress becomes secondary (softer) | `I [really](-1) mean it.` → `ɹˌiᵊli` (from `ɹˈiᵊli`) |
| `[word](-2)` | All stress removed (fully unstressed) | `I [really](-2) mean it.` → `ɹiᵊli` |
| `[word](+1)` / `(+2)` | Unstressed or secondary becomes primary (emphasis) | `I saw [the](+2) one.` → `ðˈə` (from `ðə`), i.e. "THEE one" |

A nudge only changes a word whose stress can move that way. `[really](+2)` does
nothing, because "really" already carries primary stress. Nudges can't change *which*
syllable is stressed, so they can't fix "present"; that takes phonemes.

## The pronunciation file: every occurrence

`--pronunciations FILE` applies a `word=replacement` list to every slide before speech
is generated. It's the right fix for something that's wrong everywhere: acronyms, product
names, your own name.

Common tech terms the voice gets wrong are fixed for you already, in every deck: AI ("ay
eye"), API, APIs, AWS, JSON ("jay-son"), SAML, LDAP ("el-dap"), SOC ("sock"), CISO, OWASP,
DoS, SASE ("sassy"), CASB, FIPS, PaaS, PoC, 2FA, IPv4, IPv6, PostgreSQL and OPSWAT. A rule
for the same word in your file replaces the built-in one (for example
`AI=artificial intelligence`). The list is `BUILTIN_PRONUNCIATIONS` in `narrate.py`.

```
# Lines starting with # are comments. Blank lines are ignored.
NGINX=engine x
NVMe=N V M E
SQL=sequel
Kubernetes=[Kubernetes](/kˌubəɹnˈɛtiz/)
```

Rules (all enforced by `narrate.py`, all covered by `test/test_text.py`):

- **Whole words only.** `RTX=R T X` won't touch `RTXs` or `ARTX`.
- **Case-sensitive.** `SQL=sequel` leaves `sql` alone, so you can treat the acronym
  and the lowercase word differently.
- **Longest match first.** If the file has both `NVMe` and `NVMe-oF`, the longer
  entry wins where it fits, whatever order the lines are in.
- **The replacement is plain text, or an inline override.** Plain respellings
  (`engine x`, `N V M E`) are easiest and usually enough. Use `[word](/phonemes/)`
  when respelling can't get the sound.
- Replacements are applied **once**, to the original notes text. A replacement is never
  itself scanned for other entries.
- **Inline overrides in the notes win.** The file never rewrites inside a
  `[word](...)` that's already in the notes, so a one-off fix beats the global rule.
- If a word appears on two lines, the **last line wins**.
- A line without `=` is an error (the tool names the file and line), never silently ignored.

**Your personal dictionary.** Without `--pronunciations`, deck-narrator uses
`%APPDATA%\deck-narrator\pronunciations.txt` (Linux: `~/.config/deck-narrator/pronunciations.txt`)
if it exists. The GUI's **Check pronunciation** fills it in: **Use this** on a word the voice
doesn't know (or spells out) saves it there, for every deck. From the command line:

```bash
deck-narrator --phonemes "zee scaler"            # zˈi skˈAləɹ
deck-narrator --add-word Zscaler "zˈi skˈAləɹ"   # adds or replaces Zscaler=[Zscaler](/zˈi skˈAləɹ/)
```

**Your own voice.** A voice of your own (Chatterbox) reads spelling, not phonemes, so it
ignores `/phonemes/`. In `[word](/phonemes/)` the built-in voices use the phonemes and your own
voice says what's in the brackets, so put the respelling there: `Ent=[Ennt](/ˈɛnt/)` fixes
"Ent" for every voice. A plain rule like `Ent=Ennt` is read by every voice too. The GUI's
Pronunciation tab saves one for you (**Your own voice says** Ent **as** Ennt, then **Save**),
keeping any phonemes the word already has; so does the command line:

```bash
deck-narrator --say-as Ent Ennt    # Ent=[Ennt](/ˈɛnt/) if Ent had phonemes, else Ent=Ennt
```

Respell it the way it sounds: "Ennt", "Jay son", "koo ber net eez". **Use this** later keeps
the respelling.

A starter file is in `test/pronunciations.txt`. You can also keep one file per deck,
next to the deck:

```bash
deck-narrator deck.pptx --pronunciations deck.words.txt
```

## Which tool for which job

| Problem | Fix |
|---|---|
| One heteronym read wrong in one sentence ("present", "read", "live") | Inline `[word](/phonemes/)` in that slide's notes |
| An acronym or name wrong everywhere | Pronunciation file, plain respelling |
| A name that no respelling gets right | Pronunciation file, with `[word](/phonemes/)` as the replacement |
| Your own voice says a word wrong | `--say-as WORD RESPELLING` (or the Pronunciation tab), which saves `WORD=[RESPELLING](/phonemes/)` |
| A word too strong or too weak in a sentence | Inline stress nudge, `[word](-1)` or `[word](+2)` |
| A pause in the wrong place | Change the punctuation in the notes; a comma or period is a pause |
| `[pause]` doesn't pause | Expected: stage directions are removed, not acted out. Use a period, or split the thought across slides |

## Phoneme cheat sheet

Misaki's US English alphabet is mostly IPA, with **single capital letters for the
diphthongs**, so one sound is always one character. Every example below is real
tool output:

**Stress marks** go just before the stressed vowel's syllable: `ˈ` primary, `ˌ`
secondary. `əbˈWt` = a-BOUT.

| Symbol | Sound | Example | | Symbol | Sound | Example |
|---|---|---|---|---|---|---|
| `A` | s**ay** | `sˈA` | | `ɪ` | b**i**t | `bˈɪt` |
| `I` | h**igh** | `hˈI` | | `i` | b**ee**t | `bˈit` |
| `W` | h**ow** | `hˌW` | | `ɛ` | b**e**d | `bˈɛd` |
| `Y` | b**oy** | `bˈY` | | `æ` | c**a**t | `kˈæt` |
| `O` | g**o** | `ɡˌO` | | `ʌ` | b**u**t | `bˌʌt` |
| `ɑ` | f**a**ther, l**o**t | `fˈɑðəɹ` | | `ʊ` | b**oo**k | `bˈʊk` |
| `ɔ` | c**au**ght | `kˈɔt` | | `u` | b**oo**t | `bˈut` |
| `ɜɹ` | b**ir**d | `bˈɜɹd` | | `ə` | **a**bout | `əbˈWt` |
| `ᵊ` | barely-there schwa | `pɹˈɛzᵊnt` | | `ᵻ` | reduced "i" | `ɹˈOzᵻz` (roses) |

| Symbol | Sound | Example | | Symbol | Sound | Example |
|---|---|---|---|---|---|---|
| `ɹ` | **r** | `ɹˈɛd` | | `ŋ` | si**ng** | `sˈɪŋ` |
| `θ` | **th**in | `θˈɪn` | | `ð` | **th**is | `ðˈɪs` |
| `ʃ` | **sh**ip | `ʃˈɪp` | | `ʒ` | mea**s**ure | `mˈɛʒəɹ` |
| `ʧ` | **ch**urch | `ʧˈɜɹʧ` | | `ʤ` | **j**udge | `ʤˈʌʤ` |
| `j` | **y**es | `jˈɛs` | | `ɡ` | **g**o (IPA ɡ, not keyboard g) | `ɡˌO` |
| `T` | flapped t, bu**tt**er | `bˈʌTəɹ` | | `n` (syllabic) | bu**tt**on | `bˈʌtn` |

Watch out for:

- **`ɡ` is not `g`.** IPA ɡ (U+0261) and the keyboard g look nearly identical. Copy from
  `--phonemes` output instead of typing.
- **`j` is the "y" sound**, never "j". The "j" sound is `ʤ`.
- **`ɹ`, not `r`**, for the American r.

## British voices

British voices (`bf_*`, `bm_*`) go through misaki's British front end, which has its own
phoneme set. An override must use the phonemes of the voice that speaks it, so look phonemes
up with that voice:

```bash
deck-narrator --voice bf_emma --phonemes "I got you a present."
```

The differences that matter, from the tool:

| Word | American (`af_*`, `am_*`) | British (`bf_*`, `bm_*`) |
|---|---|---|
| cat | `kˈæt` | `kˈat` (`a`, not `æ`) |
| go | `ɡˌO` | `ɡˌQ` (`Q` is the British "oh") |
| lot | `lˈɑt` | `lˈɒt` |
| car | `kˈɑɹ` | `kˈɑː` (no r after a vowel; `ː` = long) |
| butter | `bˈʌTəɹ` | `bˈʌtə` (no flap `T`) |
| bath | `bˈæθ` | `bˈɑːθ` |
| you | `ju` | `juː` |

Because British uses plain `a`, phoneme output can look like an English word: unstressed
"and" comes out as `and`. That's the phonemes for "and", not a word that slipped through.

In a deck that switches between an American and a British voice
([Switching voices](GUIDE.md#switching-voices)), an override inside a British
part needs British phonemes, and `--show-phonemes` shows each part in its own voice's set.

## Common heteronyms

All from `deck-narrator --phonemes`. Pick the column you want and paste it in:
`[word](/.../)`.

Each phoneme string came from `--phonemes` on a sentence where the tagger got it right.

| Word | Reading A | Reading B |
|---|---|---|
| present | noun/adj. "PREZ-ent" (a present) `pɹˈɛzᵊnt` | verb "pri-ZENT" (to present it) `pɹizˈɛnt` |
| record | noun "REK-ord" (a record) `ɹˈɛkəɹd` | verb "ri-KORD" (to record it) `ɹəkˈɔɹd` |
| object | noun "OB-ject" (an object) `ˈɑbʤəkt` | verb "ob-JECT" (I object) `əbʤˈɛkt` |
| content | noun "CON-tent" (the content) `kˈɑntɛnt` | adjective "con-TENT" (I am content) `kəntˈɛnt` |
| live | adjective "LYVE" (a live demo) `lˈIv` | verb "LIV" (where you live) `lˈɪv` |
| read | present tense "REED" (I will read it) `ɹˈid` | past tense "RED" (yesterday I read it) `ɹˈɛd` |
| lead | verb "LEED" (lead the team) `lˈid` | the metal "LED" `lˈɛd`, see below |
| close | verb "KLOZE" (close the tab) `klˈOz` | adjective "KLOSE" (close to home) `klˈOs` |
| minute | noun "MIN-it" (one minute) `mˈɪnət` | adjective "my-NOOT" (the details are minute) `mInˈut` |
| wind | noun "WIND" (the wind blew) `wˈɪnd` | verb "WYND" (wind it up) `wˈInd` |

### Real misreads, and how to get the right phonemes anyway

These came up while building the table above. They show the kind of
context that fools the tagger:

| Notes text | Tool said | Should be | Why |
|---|---|---|---|
| share your screen or present, ... | `pɹˈɛzᵊnt` (noun) | `pɹizˈɛnt` | verb with no object after it (the worked example above) |
| I read books every day. | `ɹˈɛd` (past) | `ɹˈid` | "read" without a helper verb looks like past tense |
| made of lead / heavy as lead | `lˈid` | `lˈɛd` | the tool never picks the metal reading in any sentence |
| a minute detail / minute details | `mˈɪnət` | `mInˈut` | adjective before a noun gets the noun reading |

When no sentence gets the reading you want (the metal "lead"), **look up a homophone
instead**: `deck-narrator --phonemes "led"` prints `lˈɛd`, so write `[lead](/lˈɛd/)`.
Verified:

```
$ deck-narrator --phonemes "I [read](/ɹˈid/) books every day. Made of [lead](/lˈɛd/)."
ˌI ɹˈid bˈʊks ˈɛvəɹi dˈA. mˌAd ʌv lˈɛd.
```

## Mistakes and what happens

| You typed | What happens | Fix |
|---|---|---|
| `[present] (/pɹizˈɛnt/)` (space before `(`) | **The tool stops before rendering:** `slide N: pronunciation override ... has a space between ] and (`. Without that check, `[present]` would be stripped as a stage direction and the voice would read the slashes aloud | Remove the space |
| `[present](pɹizˈɛnt)` (no slashes) | Not treated as phonemes: the word is read normally and the parenthesized text is dropped. No error, so check with `--show-phonemes`. (Verified: `Give me a [present](pɹizˈɛnt) now.` is still read `pɹˈɛzᵊnt`.) | Add the slashes: `(/pɹizˈɛnt/)` |
| `[present](/ pɹizˈɛnt /)` (spaces inside) | Works, with a slightly longer gap after the word | Remove the inner spaces |
| A keyboard `g` instead of IPA `ɡ` | That sound may come out wrong or be skipped | Copy phonemes from `--phonemes` |
| A pronunciation-file line with no `=` | The tool stops: `file:line: expected word=replacement` | Fix or comment out the line |
| `[pause]`, `[Slide 3]`, `[laughs]` | Removed from the spoken text, on purpose | That's what stage directions are for |
| `[click]`, `[voice: ...]` | Never spoken: they advance a build or switch voice ([Animation builds](GUIDE.md#animation-builds)) | |
| An American override inside a British voice's part | The British voice is handed American phonemes for that word. No error, so look at `--show-phonemes` | Look up with `--voice bf_...` ([British voices](#british-voices)) |

## Order of operations

What happens to a slide's notes, step by step (see `read_deck`, `clean_notes`,
`apply_pronunciations` and `synthesize` in `narrate.py`):

1. Raw notes are read from the slide (hidden slides never get this far).
2. **Check:** a detached override (`[word] (/.../)`) stops the run with the slide number.
3. The notes are split at `[click]` and `[voice: name]` markers into parts, each with a
   build step and a voice ([Animation builds](GUIDE.md#animation-builds)).
4. In each part, stage directions are removed: any other `[...]` **not** directly followed
   by `(`.
5. Whitespace is collapsed; spaces left before punctuation are removed.
6. The built-in fixes and then the pronunciation file are applied (whole word,
   case-sensitive, longest first; the file's rule wins for a word in both).
7. Neighbouring parts on the same build state with the same voice are joined.
8. Each part is split into sentences, packed into chunks of 350 characters or fewer.
9. Each chunk goes through misaki for that part's voice (honoring inline overrides), then Kokoro.

`--show-phonemes` runs steps 1 to 7 and then misaki, then stops, so it shows exactly
what step 9 will say, one line per part, labeled with its voice and click.
