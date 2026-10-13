# Deck Narrator on Linux

Debian and Ubuntu get a one-step setup. On other distributions, see the end of this page.

## Install

```bash
git clone https://github.com/mikesimone/deck-narrator.git ~/deck-narrator
~/deck-narrator/setup.sh             # add --ms-fonts for Microsoft's core fonts, see below
```

`setup.sh` installs LibreOffice, ffmpeg and fonts with apt, installs
[uv](https://docs.astral.sh/uv/) if it's missing, creates `.venv`, and links
`~/.local/bin/deck-narrator` and `~/.local/bin/deck-narrator-gui`. It uses an NVIDIA GPU if
`nvidia-smi` works, and the CPU otherwise.

It can be re-run safely, and it pre-downloads the voice model (about 330 MB) so the first
real run doesn't stall. Details: [What gets installed](REFERENCE.md#what-gets-installed).

**Fonts.** `--ms-fonts` also installs Microsoft's core fonts (Georgia, Arial, Verdana, Times;
it accepts their EULA for you). Without them, LibreOffice substitutes look-alikes and text
can wrap differently from PowerPoint. To check a font your deck uses:
`fc-match "Font Name"`. To add one, copy it into `~/.local/share/fonts/` and run
`fc-cache -f`.

## Make a video

The window:

```bash
deck-narrator-gui
```

Click **Browse...**, pick the deck, and click **Make video**. [Using Deck
Narrator](GUIDE.md) explains the rest.

Or the command line:

```bash
deck-narrator ~/path/to/deck.pptx
```

That writes `~/path/to/deck.mp4` next to the deck. [Reference: Run it](REFERENCE.md#run-it)
has a typical check-then-render loop, and [Every option](REFERENCE.md#every-option) lists
the rest.

## Updating

```bash
git -C ~/deck-narrator pull && ~/deck-narrator/setup.sh
```

## Other distributions

Install LibreOffice (Impress), ffmpeg and Python's tkinter with your package manager, then run
the rest of `setup.sh` by hand. It's short.
