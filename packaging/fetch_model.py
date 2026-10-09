#!/usr/bin/env python3
"""Copy the Kokoro-82M model and every voice into a folder, for bundling.

  python packaging/fetch_model.py dist/deck-narrator/model

narrate.py uses a model/ folder next to the program instead of downloading (see
local_model_dir), so an install that ships one works offline from the first run.
The Windows installer (MSI) is built this way.
"""
import shutil
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "hexgrad/Kokoro-82M"

dest = Path(sys.argv[1])
snapshot_download(REPO_ID, local_dir=dest, allow_patterns=["config.json", "kokoro-v1_0.pth", "voices/*.pt"])
shutil.rmtree(dest / ".cache", ignore_errors=True)     # huggingface_hub's download bookkeeping
voices = sorted((dest / "voices").glob("*.pt"))
size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file()) / 2**20
print(f"{dest}: model + {len(voices)} voices, {size:.0f} MB")
if not voices or not (dest / "kokoro-v1_0.pth").is_file():
    sys.exit("fetch_model: incomplete download")
