# PyInstaller spec for the standalone build: one folder, deck-narrator/, holding the
# command-line program (deck-narrator[.exe]) and the GUI (deck-narrator-gui[.exe]),
# which share one copy of the libraries.
# Build from the repo root:  pyinstaller packaging/deck-narrator.spec
# The GitHub Actions workflow (.github/workflows/ci.yml) builds the Windows zip with this,
# and on macOS the app, "Deck Narrator.app", whose main program is the GUI.
import os
import sys

from PyInstaller.utils.hooks import collect_all, copy_metadata

MAC = sys.platform == "darwin"
# PyInstaller turns the PNG into the Mac's .icns (it needs Pillow, which the venv has).
ICON = os.path.join(SPECPATH, "deck-narrator.png" if MAC else "deck-narrator.ico")

datas, binaries, hiddenimports = [], [], []
# Packages that load data files, plugins or entry points at runtime.
for pkg in ("kokoro", "misaki", "espeakng_loader", "en_core_web_sm", "spacy", "thinc",
            "phonemizer", "language_tags", "segments", "csvw", "pptx", "pypdfium2", "pypdfium2_raw"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
# spaCy finds the model, and transformers checks versions, through package metadata.
for pkg in ("en_core_web_sm", "spacy", "transformers", "tokenizers", "huggingface_hub",
            "safetensors", "tqdm", "regex", "requests", "numpy", "torch", "filelock", "packaging", "pyyaml"):
    datas += copy_metadata(pkg)

a = Analysis(
    ["../narrate.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["builds"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="deck-narrator", console=True,
          icon=ICON)

# The GUI only builds command lines and runs the program above, so it needs none of
# the voice stack; it imports narrate.py just for its constants and the dependency checks.
g = Analysis(
    ["../gui.py"],
    pathex=[".."],
    datas=[(ICON, "."), (os.path.join(SPECPATH, "deck-narrator.png"), ".")],
    hiddenimports=["builds"],
    excludes=["torch", "kokoro", "misaki", "spacy", "thinc", "transformers", "numpy", "scipy",
              "soundfile", "huggingface_hub", "pypdfium2", "pptx", "lxml", "matplotlib", "IPython", "pytest"],
)
gpyz = PYZ(g.pure)
gexe = EXE(gpyz, g.scripts, [], exclude_binaries=True, name="deck-narrator-gui", console=False,
           icon=ICON)

if not MAC:
    coll = COLLECT(exe, a.binaries, a.datas, gexe, g.binaries, g.datas, name="deck-narrator")
else:
    # The GUI first: the app bundle launches the first program it holds.
    coll = COLLECT(gexe, g.binaries, g.datas, exe, a.binaries, a.datas, name="deck-narrator")
    app = BUNDLE(
        coll,
        name="Deck Narrator.app",
        icon=ICON,
        bundle_identifier="io.github.mikesimone.deck-narrator",
        info_plist={
            "CFBundleDisplayName": "Deck Narrator",
            "CFBundleShortVersionString": os.environ.get("DECK_NARRATOR_VERSION", "0"),
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            # Shown when the app first asks to drive Keynote, which draws the slides.
            "NSAppleEventsUsageDescription": "Deck Narrator uses Keynote to draw your slides.",
        },
    )
