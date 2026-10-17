"""Speaks text in a person's own voice with Chatterbox (Resemble AI), for deck-narrator.

This runs in the separate Python environment that `deck-narrator --install-own-voice`
sets up, not in deck-narrator's own Python, because Chatterbox needs a different torch
and transformers. deck-narrator starts it once per run and talks to it with one JSON
object per line:

  -> {"cmd": "load", "voice": "mike", "dir": "/path/to/my-voices/mike"}
  <- {"ok": true}
  -> {"cmd": "say", "text": "Hello there.", "seed": 1234, "out": "/tmp/x.wav"}
  <- {"ok": true, "seconds": 1.4, "tries": 1}
  any failure: <- {"error": "what went wrong"}

A voice folder holds reference.* (a 10-30 second recording of the speaker), and may hold
t3.safetensors (a fine-tuned T3, the part that learns rhythm and phrasing) and voice.json
({"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "timbre_reference":
"timbre_reference.wav"}). A timbre reference, when there is one, sets how the voice sounds
(the vocoder) while reference.* still sets how it speaks (T3).

Chatterbox sometimes stops a word or two early. When faster-whisper is installed, each
clip is transcribed and, if its last word or a chunk of the text is missing, spoken again
with the next seed (up to MAX_TRIES), so the result is still the same every run.

  python -I own_voice_worker.py --device auto       serve requests on stdin
  python -I own_voice_worker.py --prefetch          download the models, then exit
  python -I own_voice_worker.py --prefetch-check    download only the speech checker
"""
import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

DEFAULTS = {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8}
AUDIO = (".wav", ".flac", ".mp3", ".ogg")
WHISPER = "base.en"         # faster-whisper model for the cut-off check (about 145 MB)
MAX_TRIES = 3               # seeds tried per clip before keeping the best one
FADE_OUT = 0.02             # seconds faded at the end of each clip, so it never ends on a click


def reference_of(folder):
    for ext in AUDIO:
        p = Path(folder) / f"reference{ext}"
        if p.is_file():
            return p
    raise FileNotFoundError(f"no reference recording (reference.wav) in {folder}")


def timbre_of(folder):
    """voice.json's timbre_reference, if it names a file in the voice folder."""
    p = Path(folder) / "voice.json"
    if not p.is_file():
        return None
    name = json.loads(p.read_text(encoding="utf-8")).get("timbre_reference")
    if not name:
        return None
    t = (Path(folder) / Path(str(name)).name)
    if not t.is_file():
        raise FileNotFoundError(f"voice.json names timbre_reference {name!r}, which isn't in {folder}")
    return t


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


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("'", "").replace("\u2019", ""))


def heard_ok(expected, heard):
    """(passes, score) for a transcript against the text it should say. Numbers can come
    back spelled out, so they only count loosely."""
    want, got = words(expected), words(heard)
    if not want:
        return True, 1.0
    if not got:
        return False, 0.0
    low = sum(1 for w in want if not w.isdigit())            # a number is at least one word
    high = len(want) + 4 * sum(1 for w in want if w.isdigit()) + 3
    coverage = min(1.0, len(got) / max(1, low))
    last = want[-1]
    if last.isdigit():
        last_ok = True
    else:
        last_ok = any(difflib.SequenceMatcher(None, last, w).ratio() >= 0.75 for w in got[-3:])
    ok = last_ok and coverage >= 0.7 and len(got) <= high
    return ok, (last_ok, coverage if len(got) <= high else 0.5 * coverage)


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
        self.checker = load_checker()
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
            self.prepare(folder, settings["exaggeration"])
            self.conds[folder] = self.model.conds
        self.model.conds = self.conds[folder]
        self.voice = (folder, settings)

    def prepare(self, folder, exaggeration):
        """Chatterbox's prepare_conditionals, except that with a timbre reference the vocoder
        takes that recording and T3 still takes reference.*."""
        import torch
        ref, timbre = reference_of(folder), timbre_of(folder)
        m = self.model
        m.prepare_conditionals(str(timbre or ref), exaggeration=exaggeration)
        if timbre:
            import librosa
            from chatterbox.models.s3tokenizer import S3_SR
            from chatterbox.models.t3.modules.cond_enc import T3Cond
            w16 = librosa.load(str(ref), sr=S3_SR)[0]
            tok, _ = m.s3gen.tokenizer.forward([w16[:m.ENC_COND_LEN]], max_len=m.t3.hp.speech_cond_prompt_len)
            ve = torch.from_numpy(m.ve.embeds_from_wavs([w16], sample_rate=S3_SR)).mean(0, keepdim=True)
            m.conds.t3 = T3Cond(speaker_emb=ve, cond_prompt_speech_tokens=torch.atleast_2d(tok),
                                emotion_adv=exaggeration * torch.ones(1, 1, 1)).to(device=m.device)

    def generate(self, text, s):
        """ChatterboxTTS.generate (0.1.7), plus three silence tokens before the vocoder, as
        Chatterbox Turbo does: without them the last sound is often cut off."""
        import torch
        import torch.nn.functional as F
        from chatterbox.models.s3gen.const import S3GEN_SIL
        from chatterbox.models.s3tokenizer import drop_invalid_tokens
        from chatterbox.models.t3.modules.cond_enc import T3Cond
        from chatterbox.tts import punc_norm
        m = self.model
        if s["exaggeration"] != m.conds.t3.emotion_adv[0, 0, 0]:
            c = m.conds.t3
            m.conds.t3 = T3Cond(speaker_emb=c.speaker_emb, cond_prompt_speech_tokens=c.cond_prompt_speech_tokens,
                                emotion_adv=s["exaggeration"] * torch.ones(1, 1, 1)).to(device=m.device)
        tokens = m.tokenizer.text_to_tokens(punc_norm(text)).to(m.device)
        if s["cfg_weight"] > 0.0:
            tokens = torch.cat([tokens, tokens], dim=0)
        tokens = F.pad(tokens, (1, 0), value=m.t3.hp.start_text_token)
        tokens = F.pad(tokens, (0, 1), value=m.t3.hp.stop_text_token)
        with torch.inference_mode():
            speech = m.t3.inference(t3_cond=m.conds.t3, text_tokens=tokens, max_new_tokens=1000,
                                    temperature=s["temperature"], cfg_weight=s["cfg_weight"],
                                    repetition_penalty=1.2, min_p=0.05, top_p=1.0)
            speech = drop_invalid_tokens(speech[0])
            speech = speech[speech < 6561].to(m.device)
            speech = torch.cat([speech, torch.tensor([S3GEN_SIL] * 3, dtype=speech.dtype, device=m.device)])
            wav, _ = m.s3gen.inference(speech_tokens=speech, ref_dict=m.conds.gen)
            wav = wav.squeeze(0).detach().cpu().numpy()
            wav = m.watermarker.apply_watermark(wav, sample_rate=m.sr)
        audio = wav.astype("float32")
        n = min(len(audio), int(FADE_OUT * m.sr))
        if n:
            import numpy as np
            audio[-n:] *= np.linspace(1.0, 0.0, n, dtype="float32")
        return audio

    def hear(self, audio):
        import librosa
        w16 = librosa.resample(audio, orig_sr=self.model.sr, target_sr=16000)
        segs, _ = self.checker.transcribe(w16, language="en", beam_size=1, vad_filter=False,
                                          condition_on_previous_text=False)
        return " ".join(seg.text for seg in segs).strip()

    def say(self, text, seed, out):
        import soundfile as sf
        import torch
        if not self.voice:
            raise RuntimeError("no voice loaded")
        _, s = self.voice
        best = None
        for k in range(MAX_TRIES if self.checker else 1):
            torch.manual_seed(int(seed) + k)
            audio = self.generate(text, s)
            if not self.checker:
                best = (None, audio, k + 1)
                break
            heard = self.hear(audio)
            ok, score = heard_ok(text, heard)
            if ok:
                best = (score, audio, k + 1)
                break
            print(f"Your voice cut it short (heard: {heard[-60:]!r}); trying again.", file=sys.stderr, flush=True)
            if best is None or score > best[0]:
                best = (score, audio, k + 1)
        _, audio, tries = best
        sf.write(out, audio, self.model.sr, subtype="FLOAT")
        return len(audio) / self.model.sr, tries


def load_checker():
    """faster-whisper on the processor, or None when it isn't installed (a 1.3.0 setup)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("The cut-off check isn't installed; Repair in Settings adds it.", file=sys.stderr, flush=True)
        return None
    return WhisperModel(WHISPER, device="cpu", compute_type="int8", cpu_threads=min(4, os.cpu_count() or 1))


def gpu_info():
    import torch
    mps = getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available()
    return {"cuda": torch.cuda.is_available(), "mps": mps,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    p.add_argument("--prefetch", action="store_true", help="download the models, check they load, and exit")
    p.add_argument("--prefetch-check", action="store_true", help="download only the cut-off checker, and exit")
    args = p.parse_args()

    # stdout carries the replies; anything the libraries print goes to stderr (the log).
    reply_to = sys.stdout
    sys.stdout = sys.stderr

    def reply(**msg):
        reply_to.write(json.dumps(msg) + "\n")
        reply_to.flush()

    if args.prefetch or args.prefetch_check:
        if args.prefetch:
            from chatterbox.tts import ChatterboxTTS
            ChatterboxTTS.from_pretrained("cpu")
        from faster_whisper import WhisperModel
        WhisperModel(WHISPER, device="cpu", compute_type="int8")
        reply(ok=True, **gpu_info())
        return 0

    try:
        device = pick_device(args.device)
        print(f"Loading Chatterbox on {device}...", file=sys.stderr, flush=True)
        speaker = Speaker(device)
    except Exception as e:
        reply(error=f"couldn't load Chatterbox: {type(e).__name__}: {e}")
        return 1
    reply(ready=True, device=device, sr=speaker.model.sr, check=speaker.checker is not None)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            if req["cmd"] == "load":
                speaker.load(req["dir"])
                reply(ok=True)
            elif req["cmd"] == "say":
                seconds, tries = speaker.say(req["text"], req.get("seed", 0), req["out"])
                reply(ok=True, seconds=seconds, tries=tries)
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
