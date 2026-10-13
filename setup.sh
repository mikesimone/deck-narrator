#!/usr/bin/env bash
# One-time, re-runnable setup for deck-narrator on Debian/Ubuntu or macOS (with Homebrew).
#   ./setup.sh             system packages (apt, or brew on a Mac), Python deps in ./.venv (uv), wrapper on PATH
#   ./setup.sh --ms-fonts  also install Microsoft's core fonts (Georgia, Arial, Times, Verdana),
#                          accepting their EULA, so decks made on Windows render in their own fonts
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname)" == "Darwin" ]]; then
    # macOS: Homebrew for ffmpeg and LibreOffice (uv's Python already includes Tk).
    if ! command -v brew >/dev/null; then
        echo "Homebrew is needed: see https://brew.sh, then run this again." >&2
        exit 1
    fi
    command -v ffmpeg >/dev/null || brew install ffmpeg
    [[ -d /Applications/LibreOffice.app || -d "$HOME/Applications/LibreOffice.app" ]] || brew install --cask libreoffice
else
    # Refresh the package lists first: a stale list asks mirrors for package versions they no longer have.
    sudo apt-get update -q
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-core ffmpeg \
        fonts-dejavu fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea \
        python3-tk
    if [[ "${1:-}" == "--ms-fonts" ]]; then
        echo ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true | sudo debconf-set-selections
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ttf-mscorefonts-installer
    fi
fi

if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
[[ -x "$here/.venv/bin/python" ]] || uv venv --python 3.12 "$here/.venv"
# torch first, from PyTorch's own index: CUDA if there's an NVIDIA GPU, CPU otherwise.
# On a Mac, PyPI's torch already includes Apple Silicon GPU (Metal) support.
if [[ "$(uname)" == "Darwin" ]]; then
    uv pip install --python "$here/.venv/bin/python" torch
else
    if command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1; then
        index=https://download.pytorch.org/whl/cu128
    else
        index=https://download.pytorch.org/whl/cpu
    fi
    uv pip install --python "$here/.venv/bin/python" --index-url "$index" torch
fi
uv pip install --python "$here/.venv/bin/python" -r "$here/requirements.txt"

mkdir -p "$HOME/.local/bin"
ln -sf "$here/deck-narrator" "$HOME/.local/bin/deck-narrator"
ln -sf "$here/deck-narrator-gui" "$HOME/.local/bin/deck-narrator-gui"

# Pre-fetch the model + default voice so the first real run doesn't stall on a download.
"$here/.venv/bin/python" - <<'PY'
from huggingface_hub import hf_hub_download
for f in ("config.json", "kokoro-v1_0.pth", "voices/af_heart.pt"):
    hf_hub_download("hexgrad/Kokoro-82M", f)
print("Kokoro-82M cached.")
PY
echo "OK: run  deck-narrator path/to/deck.pptx   (~/.local/bin must be on PATH)"
