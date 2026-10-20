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
({"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "pause_scale": 1.0,
"speed": 1.0, "timbre_reference": "timbre_reference.wav"}). A timbre reference, when there
is one, sets how the voice sounds (the vocoder) while reference.* still sets how it speaks
(T3). "s3gen": "s3gen.safetensors" names fine-tuned S3Gen weights (the vocoder side), loaded
over the stock ones like t3.safetensors. pause_scale lengthens the pauses inside each clip (here); speed slows or speeds the
whole clip without changing the pitch (deck-narrator does that, with ffmpeg).

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

DEFAULTS = {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "pause_scale": 1.0, "speed": 1.0,
            "breath_db": 0.0, "depop": 0.0}
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


def s3gen_of(folder):
    """voice.json's s3gen, if it names a file in the voice folder."""
    p = Path(folder) / "voice.json"
    name = json.loads(p.read_text(encoding="utf-8")).get("s3gen") if p.is_file() else None
    if not name:
        return None
    s = Path(folder) / Path(str(name)).name
    if not s.is_file():
        raise FileNotFoundError(f"voice.json names s3gen {name!r}, which isn't in {folder}")
    return s


def plain_state(state):
    """A saved T3 or S3Gen state dict, without the prefixes training scripts tend to add."""
    if "model" in state and not hasattr(state["model"], "shape"):
        state = state["model"][0]
    for prefix in ("module.", "t3.", "s3gen."):
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


def depop(wav, sr, hp_hz=70, lf_hz=150, over_db=6.0, attack_ms=10, release_ms=60):
    """Thud fix. S3Gen sometimes starts a word after a pause with a low-frequency burst (a plosive 'pop' learned from
    a recording made without a pop filter), heard as a thud. 1) a gentle 2nd-order high-pass at hp_hz (the training
    audio was high-passed at 70 Hz anyway); 2) a dynamic de-pop: the < lf_hz band is split off (zero-phase low-pass,
    so lf + rest sums back exactly) and turned down only where it rises more than over_db above the clip's typical
    speech level (> 300 Hz) and above the rest of the spectrum, with a smooth gain (no gating). Voiced speech, whose
    fundamental sits in that band, is untouched because it never exceeds the speech level by 6 dB."""
    import numpy as np
    from scipy.signal import butter, sosfiltfilt
    x = np.asarray(wav, dtype=np.float64)
    if len(x) < sr // 10: return np.asarray(wav, dtype=np.float32)
    x = sosfiltfilt(butter(2, hp_hz, btype="high", fs=sr, output="sos"), x)
    lf = sosfiltfilt(butter(4, lf_hz, btype="low", fs=sr, output="sos"), x); rest = x - lf
    hi = sosfiltfilt(butter(4, 300, btype="high", fs=sr, output="sos"), x)
    hop = int(sr * 0.005); n = len(x) // hop
    if n < 4: return x.astype(np.float32)
    db = lambda v: 20 * np.log10(np.sqrt((v[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    L, H = db(lf), db(hi); sp = np.median(H[H > np.percentile(H, 99) - 30])
    over = np.maximum(0, L - np.maximum(sp + over_db, H + 3))           # how far the low band sticks out
    g = 10 ** (-over / 20)
    a, r = np.exp(-1 / max(1, attack_ms / 5)), np.exp(-1 / max(1, release_ms / 5)); s = np.ones(n); cur = 1.0
    for i in range(n):                                                  # fast attack (down), slow release (up)
        cur = a * cur + (1 - a) * g[i] if g[i] < cur else r * cur + (1 - r) * g[i]; s[i] = cur
    gain = np.interp(np.arange(len(x)), np.arange(n) * hop + hop / 2, s)
    return (rest + gain * lf).astype(np.float32)


def find_breaths(wav, sr, min_ms=150, max_level_db=0.0, min_level_db=-45.0, lf_ratio_db=-12.0, min_flat=0.08,
                 cen_lo=900, cen_hi=4500, gap_ms=30):
    """Breath segments, from the spectrum (no ASR, no pitch tracker): 10 ms frames whose energy below 400 Hz is at
    least lf_ratio_db under the 1-5 kHz band (no voicing harmonics), that are noise-like (spectral flatness over
    0.5-6 kHz >= min_flat), centred between cen_lo and cen_hi (so /s/ and /sh/, which sit higher, are excluded),
    between min_level_db and max_level_db re the clip's median speech frame, in runs of at least min_ms (/f/, /h/ and
    stop bursts are shorter), with no voiced frame within gap_ms after the run ends (an /h/ runs straight into its
    vowel; an inhale leaves a gap). Returns [(start_sample, end_sample)]."""
    import numpy as np
    import librosa
    x = np.asarray(wav, dtype=np.float32); hop = int(sr * 0.01); n = len(x) // hop
    if n < 10: return []
    S = np.abs(librosa.stft(x, n_fft=1024, hop_length=hop, center=True))[:, :n] ** 2
    f = librosa.fft_frequencies(sr=sr, n_fft=1024); band = lambda lo, hi: S[(f >= lo) & (f < hi)]
    db = lambda v: 10 * np.log10(v + 1e-12)
    low, mid = db(band(60, 400).sum(0)), db(band(1000, 5000).sum(0)); tot = db(S.sum(0))
    B = band(500, 6000); flat = np.exp(np.mean(np.log(B + 1e-12), 0)) / (np.mean(B, 0) + 1e-12)
    cen = (f[:, None] * S).sum(0) / (S.sum(0) + 1e-12)
    voiced = (low - mid > 0) & (tot > np.percentile(tot, 99) - 35)
    sp = np.median(tot[voiced]) if voiced.any() else np.percentile(tot, 90)
    cand = (low - mid < lf_ratio_db) & (flat >= min_flat) & (cen >= cen_lo) & (cen <= cen_hi) & (tot < sp + max_level_db) & (tot > sp + min_level_db)
    cand = np.convolve(cand.astype(float), np.ones(3) / 3, "same") > 0.5        # bridge single-frame gaps
    out, i = [], 0
    while i < n:
        if cand[i]:
            j = i
            while j < n and cand[j]: j += 1
            if (j - i) * 10 >= min_ms and not voiced[j:j + gap_ms // 10 + 1].any(): out.append((i * hop, j * hop))
            i = j
        else: i += 1
    return out


def tame_breaths(wav, sr, breath_db=-9.0, max_ms=400, ramp_ms=30):
    """Quieter breaths, never removed: every find_breaths() segment is turned down by breath_db (negative dB) with
    ramp_ms raised-cosine ramps inside the segment (no hard gating), and a breath longer than max_ms is shortened to max_ms by cutting
    its middle with a 10 ms crossfade. breath_db 0 = off."""
    import numpy as np
    x = np.asarray(wav, dtype=np.float32).copy()
    if not breath_db: return x
    segs = find_breaths(x, sr)
    if not segs: return x
    g = np.ones(len(x), np.float32); lo = 10 ** (breath_db / 20)
    for a, b in segs:                                   # ramps sit inside the breath, so neighbouring speech is untouched
        k = min(int(sr * ramp_ms / 1000), (b - a) // 2)
        env = np.full(b - a, lo, np.float32)
        if k:
            r = (1 + np.cos(np.linspace(0, np.pi, k))) / 2 * (1 - lo) + lo   # 1 -> lo, raised cosine
            env[:k] = r; env[-k:] = r[::-1]
        g[a:b] = np.minimum(g[a:b], env)
    x *= g
    cut = int(sr * max_ms / 1000); xf = int(sr * 0.01); pieces, last = [], 0
    for a, b in segs:
        if b - a <= cut: continue
        keep = cut // 2; m1, m2 = a + keep, b - keep                            # keep the breath's start and end
        fade = np.linspace(1, 0, xf, dtype=np.float32)
        head = x[last:m1].copy(); tail = x[m2:m2 + xf].copy()
        if len(head) >= xf and len(tail) == xf: head[-xf:] = head[-xf:] * fade + tail * (1 - fade); pieces.append(head); last = m2 + xf
        else: pieces.append(x[last:m1]); last = m2
    pieces.append(x[last:])
    return np.concatenate(pieces)


def extend_pauses(x, sr, factor, min_pause=0.12, max_added=0.35, quiet_db=-35):
    """Lengthen the pauses inside a clip (runs of at least min_pause, quiet_db below its peak)
    by factor, at most max_added seconds each, by repeating the pause's own quiet audio so
    the background stays continuous. Leading and trailing silence is left alone."""
    import numpy as np
    hop = int(sr * 0.01)
    if factor <= 1.0 or len(x) < hop * 10:
        return x
    n = len(x) // hop
    env = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    quiet = 20 * np.log10(env / (env.max() + 1e-9) + 1e-12) < quiet_db
    loud = np.nonzero(~quiet)[0]
    if len(loud) < 2:
        return x
    out, last, i = [], 0, loud[0]
    while i <= loud[-1]:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j <= loud[-1] and quiet[j]:
            j += 1
        dur = (j - i) * hop / sr
        if dur >= min_pause:
            a, b = i * hop, j * hop
            mid = (a + b) // 2
            pad = np.resize(x[a:b], int(min(dur * (factor - 1), max_added) * sr)).astype("float32")
            k = min(int(sr * 0.005), len(pad) // 2)
            if k:
                pad[:k] *= np.linspace(0, 1, k, dtype="float32")
                pad[-k:] *= np.linspace(1, 0, k, dtype="float32")
            out += [x[last:mid], pad]
            last = mid
        i = j
    out.append(x[last:])
    return np.concatenate(out)


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
        self.base = {}             # part -> the stock weights, kept once a fine-tuned voice replaces them
        self.loaded = {"t3": None, "s3gen": None}   # part -> which .safetensors is loaded (None = stock)
        self.conds = {}            # voice folder -> prepared conditionals
        self.voice = None

    def load(self, folder):
        import torch
        from safetensors.torch import load_file
        folder = str(Path(folder).resolve())
        t3, s3gen = Path(folder) / "t3.safetensors", s3gen_of(folder)
        for part, path in (("t3", t3 if t3.is_file() else None), ("s3gen", s3gen)):
            want = str(path) if path else None
            if want == self.loaded[part]:
                continue
            module = getattr(self.model, part)
            if part not in self.base:
                self.base[part] = {k: v.detach().to("cpu", copy=True) for k, v in module.state_dict().items()}
            module.load_state_dict(plain_state(load_file(want)) if want else self.base[part], strict=True)
            module.to(self.device).eval()
            self.loaded[part] = want
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
        if s.get("depop"): audio = depop(audio, self.model.sr)                    # low-frequency onset thuds
        if s.get("breath_db"): audio = tame_breaths(audio, self.model.sr, s["breath_db"])  # quieter, shorter breaths
        audio = extend_pauses(audio, self.model.sr, s["pause_scale"])
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
