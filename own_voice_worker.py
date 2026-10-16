"""Speaks text in a person's own voice with Chatterbox (Resemble AI), for deck-narrator.

This runs in the separate Python environment that `deck-narrator --install-own-voice`
sets up, not in deck-narrator's own Python, because Chatterbox needs a different torch
and transformers. deck-narrator starts it once per run and talks to it with one JSON
object per line:

  -> {"cmd": "load", "voice": "mike", "dir": "/path/to/my-voices/mike"}
  <- {"ok": true}
  -> {"cmd": "say", "text": "Hello there.", "seed": 1234, "out": "/tmp/x.wav"}
  <- {"ok": true, "seconds": 1.4}
  any failure: <- {"error": "what went wrong"}

A voice folder holds reference.* (a 10-30 second recording of the speaker), and may hold
t3.safetensors (a fine-tuned T3, the part that learns rhythm and phrasing) and voice.json
({"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8}).

  python -I own_voice_worker.py --device auto       serve requests on stdin
  python -I own_voice_worker.py --prefetch          download the model, then exit
"""
import argparse
import json
import os
import sys
from pathlib import Path

DEFAULTS = {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8}
AUDIO = (".wav", ".flac", ".mp3", ".ogg")


def reference_of(folder):
    for ext in AUDIO:
        p = Path(folder) / f"reference{ext}"
        if p.is_file():
            return p
    raise FileNotFoundError(f"no reference recording (reference.wav) in {folder}")


def settings_of(folder):
    s = dict(DEFAULTS)
    p = Path(folder) / "voice.json"
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        s.update({k: float(data[k]) for k in DEFAULTS if k in data})
    return s


def plain_state(state):
    """A saved T3 state dict, without the prefixes training scripts tend to add."""
    if "model" in state and not hasattr(state["model"], "shape"):
        state = state["model"][0]
    for prefix in ("module.", "t3."):
        if state and all(k.startswith(prefix) for k in state):
            state = {k[len(prefix):]: v for k, v in state.items()}
    return state


def pick_device(choice):
    import torch
    mps = getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()
    if choice == "auto":
        return "cuda" if torch.cuda.is_available() else "mps" if mps else "cpu"
    if choice == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda, but this Python's torch can't use an NVIDIA GPU")
    if choice == "mps" and not mps:
        raise RuntimeError("--device mps, but Apple's Metal GPU isn't available")
    return choice


class Speaker:
    def __init__(self, device):
        from chatterbox.tts import ChatterboxTTS
        self.model = ChatterboxTTS.from_pretrained(device)
        self.device = device
        self.base_t3 = None        # the stock T3 weights, kept once a fine-tuned voice replaces them
        self.t3_of = None          # which t3.safetensors is loaded (None = stock)
        self.conds = {}            # voice folder -> prepared conditionals
        self.voice = None

    def load(self, folder):
        import torch
        from safetensors.torch import load_file
        folder = str(Path(folder).resolve())
        t3 = Path(folder) / "t3.safetensors"
        want = str(t3) if t3.is_file() else None
        if want != self.t3_of:
            if self.base_t3 is None:
                self.base_t3 = {k: v.detach().to("cpu", copy=True) for k, v in self.model.t3.state_dict().items()}
            state = plain_state(load_file(want)) if want else self.base_t3
            self.model.t3.load_state_dict(state, strict=True)
            self.model.t3.to(self.device).eval()
            self.t3_of = want
            if self.device == "cuda":
                torch.cuda.empty_cache()
        settings = settings_of(folder)
        if folder not in self.conds:
            self.model.prepare_conditionals(str(reference_of(folder)), exaggeration=settings["exaggeration"])
            self.conds[folder] = self.model.conds
        self.model.conds = self.conds[folder]
        self.voice = (folder, settings)

    def say(self, text, seed, out):
        import soundfile as sf
        import torch
        if not self.voice:
            raise RuntimeError("no voice loaded")
        _, s = self.voice
        torch.manual_seed(int(seed))
        wav = self.model.generate(text, exaggeration=s["exaggeration"], cfg_weight=s["cfg_weight"],
                                  temperature=s["temperature"])
        audio = wav.squeeze(0).detach().cpu().numpy().astype("float32")
        sf.write(out, audio, self.model.sr, subtype="FLOAT")
        return len(audio) / self.model.sr


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    p.add_argument("--prefetch", action="store_true", help="download the Chatterbox model, check it loads, and exit")
    args = p.parse_args()

    # stdout carries the replies; anything the libraries print goes to stderr (the log).
    reply_to = sys.stdout
    sys.stdout = sys.stderr

    def reply(**msg):
        reply_to.write(json.dumps(msg) + "\n")
        reply_to.flush()

    if args.prefetch:
        from chatterbox.tts import ChatterboxTTS
        ChatterboxTTS.from_pretrained("cpu")
        reply(ok=True)
        return 0

    try:
        device = pick_device(args.device)
        print(f"Loading Chatterbox on {device}...", file=sys.stderr, flush=True)
        speaker = Speaker(device)
    except Exception as e:
        reply(error=f"couldn't load Chatterbox: {type(e).__name__}: {e}")
        return 1
    reply(ready=True, device=device, sr=speaker.model.sr)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req["cmd"] == "load":
                speaker.load(req["dir"])
                reply(ok=True)
            elif req["cmd"] == "say":
                reply(ok=True, seconds=speaker.say(req["text"], req.get("seed", 0), req["out"]))
            elif req["cmd"] == "quit":
                break
            else:
                reply(error=f"unknown command {req['cmd']!r}")
        except Exception as e:
            reply(error=f"{type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    sys.exit(main())
