# PyInstaller spec for the standalone build (one folder: deck-narrator/deck-narrator[.exe]).
# Build from the repo root:  pyinstaller packaging/deck-narrator.spec
# The GitHub Actions workflow (.github/workflows/ci.yml) builds the Windows zip with this.
from PyInstaller.utils.hooks import collect_all, copy_metadata

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
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="deck-narrator", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="deck-narrator")
