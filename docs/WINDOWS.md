# Deck Narrator on Windows

Pick **one** way to install. If you're not sure, use the first one.

- [With Chocolatey (best)](#with-chocolatey-best)
- [With the installer](#with-the-installer)
- [Drawing the slides: PowerPoint or LibreOffice](#drawing-the-slides-powerpoint-or-libreoffice)
- [Standalone zip (no install)](#standalone-zip-no-install)
- [From source](#from-source)
- [Updating and uninstalling](#updating-and-uninstalling)

Once it's installed, open **Deck Narrator** from the Start menu, click **Browse...** to pick
your PowerPoint file, and click **Make video**. The video is saved next to the deck.
[Using Deck Narrator](GUIDE.md) explains the rest.

## With Chocolatey (best)

One command installs the same installer as below, checks its SHA-256, and skips the
SmartScreen "Windows protected your PC" step. In an admin PowerShell:

```powershell
choco install deck-narrator
```

`choco upgrade deck-narrator` updates it later. No Chocolatey yet? It's a one-line install
from [chocolatey.org/install](https://chocolatey.org/install).

winget (`winget install MikeSimone.DeckNarrator`) will work the same way once Microsoft
accepts the package.

## With the installer

Download `deck-narrator-<version>-x64.msi` from the
[Releases](https://github.com/mikesimone/deck-narrator/releases/latest) page and run it.
It installs to `Program Files\Deck Narrator` for all users, adds **Deck Narrator** to the
Start menu, and puts `deck-narrator.exe` on the system PATH. The voice model, all its voices
and ffmpeg are included (the MSI is large because of them), so nothing is downloaded when
you first make a video.

The Windows releases aren't code-signed, so Windows may warn that the installer is from an
unknown publisher. Choose **More info**, then **Run anyway**. They're built from this
repository by GitHub Actions ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)), not
on anyone's PC, and the Releases page lists each file's SHA-256.

If PowerPoint or LibreOffice is already there, the last page offers **Set up your own voice
now** instead (unticked): see [Your own voice](OWN-VOICE.md).

A silent install: `msiexec /i deck-narrator-<version>-x64.msi /qn INSTALLDEPS=1`
(`INSTALLDEPS=1` adds LibreOffice if it's needed; see the next section).

## Drawing the slides: PowerPoint or LibreOffice

Drawing the slides takes Microsoft PowerPoint or LibreOffice. If PowerPoint is installed,
Deck Narrator uses it and nothing else is needed. If not, leave **Install LibreOffice if
it's needed** ticked on the installer's last page (or press **Install LibreOffice** in the
app, or run `install-dependencies.cmd` in the install folder). It downloads LibreOffice
straight from The Document Foundation (no winget needed), checks the download's signature,
and installs only what Deck Narrator uses, leaving Office alone:

- `REGISTER_NO_MSO_TYPES=1`: LibreOffice doesn't take over `.pptx`, `.docx` or `.xlsx`, so
  they keep opening in Office.
- No Base, Math or online updater, and no desktop icon. (Writer and Calc stay, because
  Impress's PDF export crashes without them.)

## Standalone zip (no install)

`deck-narrator-windows-x64.zip` on the same Releases page is the same program without an
installer: unzip it anywhere and run `deck-narrator-gui.exe` or `deck-narrator.exe`. It
includes ffmpeg and `install-dependencies.cmd`, and downloads the voice model (about 330 MB)
the first time it speaks.

The installer and the zip both run the voice on the CPU, which is plenty fast. For NVIDIA GPU
speed, install from source.

## From source

Native PowerShell; no WSL, no Docker; uses an NVIDIA GPU if there is one:

```powershell
git clone https://github.com/mikesimone/deck-narrator.git
cd deck-narrator
.\setup.ps1 -AddToPath
```

`setup.ps1` installs LibreOffice and ffmpeg with winget if they're missing, installs
[uv](https://docs.astral.sh/uv/) if it's missing, and creates `.venv` with everything else.
`-AddToPath` puts the folder on your user PATH so `deck-narrator` works from any folder (in a
new terminal); without it, run `.\deck-narrator.cmd`. The app is `.\deck-narrator-gui.cmd`.

`setup.ps1` can be re-run safely, and pre-downloads the voice model (about 330 MB) so the
first real run doesn't stall. Details: [What gets installed](REFERENCE.md#what-gets-installed).

## Updating and uninstalling

The installed app checks GitHub once a day for a new version (you can turn this off in
**Settings**). When there is one, an **Update to x.y.z** button appears at the top; click it
and it installs the new version and reopens. With Chocolatey, `choco upgrade deck-narrator`
does the same.

Uninstall from **Settings > Apps** (or `choco uninstall deck-narrator`).
