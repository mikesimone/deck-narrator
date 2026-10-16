# Third-party notices

deck-narrator's own code (this repository) is MIT-licensed; see `LICENSE`.

## Running from source

A source install (`setup.sh` / `setup.ps1`) downloads its dependencies from PyPI,
PyTorch's index and HuggingFace onto your machine; nothing is redistributed by this
project. Each package keeps its own license.

## The Windows installer and standalone zip

The installer (MSI) and the zip on the Releases page bundle a Python runtime and these packages (and their
own dependencies, mostly MIT, BSD and Apache-2.0):

| Component | License |
|---|---|
| [kokoro](https://github.com/hexgrad/kokoro) (TTS inference) | Apache-2.0 |
| [misaki](https://github.com/hexgrad/misaki) (phonemizer) | Apache-2.0 |
| [phonemizer-fork](https://github.com/thewh1teagle/phonemizer-fork) (used by misaki) | **GPL-3.0** |
| [espeak-ng](https://github.com/espeak-ng/espeak-ng), via [espeakng-loader](https://github.com/thewh1teagle/espeakng-loader) | **GPL-3.0** |
| [num2words](https://github.com/savoirfairelinux/num2words) | LGPL-2.1 |
| [PyTorch](https://github.com/pytorch/pytorch) (CPU build) | BSD-3-Clause |
| [transformers](https://github.com/huggingface/transformers), [tokenizers](https://github.com/huggingface/tokenizers), [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 |
| [spaCy](https://github.com/explosion/spaCy), [en_core_web_sm](https://github.com/explosion/spacy-models) | MIT |
| [python-pptx](https://github.com/scanny/python-pptx) | MIT |
| Python's tkinter, with [Tcl/Tk](https://www.tcl.tk/) (the GUI) | PSF / Tcl-Tk license (BSD-style) |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) and [PDFium](https://pdfium.googlesource.com/pdfium/) | Apache-2.0 / BSD-3-Clause |
| [NumPy](https://github.com/numpy/numpy), [soundfile](https://github.com/bastibe/python-soundfile) (with libsndfile, LGPL-2.1), [lxml](https://github.com/lxml/lxml), [Pillow](https://github.com/python-pillow/Pillow) | BSD / MIT-CMU / LGPL-2.1 |

The installer also includes the [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M)
model and voices (Apache-2.0), unmodified, in `model\`. It is built with the
[WiX Toolset](https://wixtoolset.org/).

Because they include GPL-3.0 components, **the installer and the zip, as a whole, are
distributed under the terms of the GNU GPL v3.0**. Corresponding source: this repository (at the
release's tag) for deck-narrator, and each component's upstream repository linked above,
at the version recorded in the bundle's `_internal/*.dist-info` folders, which also hold
most packages' license texts. The GPL-3.0 text itself is in the install folder and the zip as
`licenses/GPL-3.0.txt`. The bundle's components are unmodified.

**ffmpeg** (Windows zip and installer, in `ffmpeg/`): the unmodified "release essentials"
build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), GPL-3.0 (it includes libx264).
Its license is `ffmpeg/LICENSE`; the corresponding source is at
[ffmpeg.org](https://ffmpeg.org/download.html) and linked from gyan.dev for that version.

**Not bundled, installed separately:** LibreOffice (MPL-2.0), downloaded from The Document
Foundation by `install-dependencies.ps1` when it's needed, or Microsoft PowerPoint.

**Downloaded at first run** (source installs and the zip; the installer already has them): the Kokoro-82M model and voices from
[hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), Apache-2.0.

## Your own voice (downloaded on request)

Nothing for it is bundled. When you set up [your own voice](docs/OWN-VOICE.md), deck-narrator
downloads, onto your machine only: [uv](https://github.com/astral-sh/uv) (MIT / Apache-2.0),
a Python 3.11 build, [Chatterbox](https://github.com/resemble-ai/chatterbox) (MIT) with its
dependencies from PyPI and PyTorch's index, each under its own license, and the
[ResembleAI/chatterbox](https://huggingface.co/ResembleAI/chatterbox) model (MIT).
