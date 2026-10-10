#!/usr/bin/env python3
"""Pre-records the GUI's default sample sentence in every English voice, so Play sample
answers at once for those. Writes DEST/<key>.wav, named the way --sample looks them up
(narrate.sample_key); the Windows builds ship DEST as samples/ next to the program.

  python packaging/prerender_samples.py dist/deck-narrator/samples
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import narrate  # noqa: E402


def main():
    import soundfile as sf
    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    text = narrate.DEFAULT_SAMPLE_TEXT
    tts = narrate.TTS("cpu")
    voices = [v for v in narrate.available_voices() if v[0] in "ab"]
    for v in voices:
        audio = tts.synthesize(v, text, 1.0)
        sf.write(dest / f"{narrate.sample_key(v, text, 1.0)}.wav", audio, narrate.SAMPLE_RATE, subtype="PCM_16")
        print(f"{v}: {len(audio) / narrate.SAMPLE_RATE:.2f}s")
    print(f"{len(voices)} samples in {dest}")


if __name__ == "__main__":
    main()
