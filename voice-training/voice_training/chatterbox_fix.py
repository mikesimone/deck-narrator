"""Drop-in fixes for chatterbox-tts 0.1.7's standard (non-Turbo) ChatterboxTTS (same file Deck Narrator uses).

generate_clean(): same as ChatterboxTTS.generate, plus two things:
  * appends 3 S3Gen silence tokens (S3GEN_SIL) after T3's speech tokens before vocoding, exactly as tts_turbo.py
    does, so the final phoneme gets frames to decay instead of being chopped mid-sound;
  * trims trailing near-silence and applies a 20 ms cosine fade-out, so a chunk never ends on a hard edge.
  Optional `speed` (< 1 slows down) applies a pitch-preserving time stretch (ffmpeg atempo, WSOLA; ffmpeg from PATH
  or the imageio-ffmpeg wheel).

stitch(): joins chunk waveforms with gaps of low room tone (not digital zero) and short fades at every edge, so
the background bed never snaps to silence (heard as a dropout) and joins never click.
"""
import shutil, subprocess, tempfile
import numpy as np, torch, torch.nn.functional as F

def _fade_tail(wav, sr, fade_ms=20, trim_db=-55):
    x = wav.copy()
    if len(x) == 0: return x
    peak = np.abs(x).max() + 1e-9; hop = int(sr * 0.01)
    env = np.array([np.abs(x[i:i + hop]).max() for i in range(0, len(x), hop)])
    loud = np.where(20 * np.log10(env / peak + 1e-12) > trim_db)[0]
    if len(loud): x = x[:min(len(x), (loud[-1] + 1) * hop + int(sr * 0.08))]  # keep 80 ms after the last real sound
    n = min(len(x), int(sr * fade_ms / 1000))
    x[-n:] *= (np.cos(np.linspace(0, np.pi, n)) + 1) / 2
    return x

def time_stretch(wav, sr, speed):
    """Pitch-preserving tempo change via ffmpeg atempo (0.5-2.0). speed < 1 = slower."""
    if abs(speed - 1) < 1e-3: return wav
    with tempfile.TemporaryDirectory() as d:
        import soundfile as sf
        sf.write(f"{d}/i.wav", wav, sr, subtype="FLOAT")
        exe = shutil.which("ffmpeg")
        if not exe:
            import imageio_ffmpeg; exe = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([exe, "-v", "error", "-y", "-i", f"{d}/i.wav", "-filter:a", f"atempo={speed}", f"{d}/o.wav"], check=True)
        return sf.read(f"{d}/o.wav")[0].astype(np.float32)

@torch.inference_mode()
def generate_clean(model, text, exaggeration=0.5, cfg_weight=0.5, temperature=0.8, repetition_penalty=1.2,
                   min_p=0.05, top_p=1.0, speed=1.0, watermark=True):
    """Returns a 1-D float32 numpy waveform at model.sr. model.conds must already be prepared."""
    from chatterbox.tts import punc_norm
    from chatterbox.models.s3tokenizer import drop_invalid_tokens
    from chatterbox.models.s3gen.const import S3GEN_SIL
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    c = model.conds.t3
    if float(c.emotion_adv.view(-1)[0]) != exaggeration:
        model.conds.t3 = T3Cond(speaker_emb=c.speaker_emb, cond_prompt_speech_tokens=c.cond_prompt_speech_tokens,
                                emotion_adv=exaggeration * torch.ones(1, 1, 1)).to(device=model.device)
    tt = model.tokenizer.text_to_tokens(punc_norm(text)).to(model.device)
    if cfg_weight > 0.0: tt = torch.cat([tt, tt], dim=0)
    tt = F.pad(F.pad(tt, (1, 0), value=model.t3.hp.start_text_token), (0, 1), value=model.t3.hp.stop_text_token)
    st = model.t3.inference(t3_cond=model.conds.t3, text_tokens=tt, max_new_tokens=1000, temperature=temperature,
                            cfg_weight=cfg_weight, repetition_penalty=repetition_penalty, min_p=min_p, top_p=top_p)[0]
    st = drop_invalid_tokens(st); st = st[st < 6561].to(model.device)
    st = torch.cat([st, torch.tensor([S3GEN_SIL] * 3, device=model.device, dtype=st.dtype)])  # let the last phoneme decay
    wav, _ = model.s3gen.inference(speech_tokens=st, ref_dict=model.conds.gen)
    wav = wav.squeeze(0).detach().cpu().numpy()
    if watermark: wav = model.watermarker.apply_watermark(wav, sample_rate=model.sr)
    wav = _fade_tail(np.asarray(wav, dtype=np.float32), model.sr)
    return time_stretch(wav, model.sr, speed) if speed != 1.0 else wav

def stitch(chunks, sr, gaps, fade_ms=10, tone_db=-62.0, seed=0):
    """chunks: list of 1-D arrays; gaps: list of seconds between them (len(chunks)-1). Gaps are filled with
    low pink-ish room tone instead of zeros; every chunk edge gets a short cosine fade."""
    rng = np.random.default_rng(seed); n = int(sr * fade_ms / 1000); out = []
    def tone(sec):
        w = rng.standard_normal(int(sr * sec)).astype(np.float32)
        w = np.convolve(w, np.ones(8) / 8, mode="same")  # soften the hiss
        return w / (np.sqrt(np.mean(w**2)) + 1e-9) * 10 ** (tone_db / 20)
    for i, c in enumerate(chunks):
        c = np.asarray(c, dtype=np.float32).copy(); k = min(n, len(c) // 2)
        if k: c[:k] *= np.linspace(0, 1, k); c[-k:] *= np.linspace(1, 0, k)
        out.append(c)
        if i < len(gaps): out.append(tone(gaps[i]))
    return np.concatenate(out)


def _norm_words(t):
    import re
    return re.sub(r"[^a-z0-9' ]", " ", t.lower()).split()

def generate_checked(model, text, asr, tries=3, seed=0, max_wer=0.25, **kw):
    """generate_clean() with a final-word check: T3 sometimes stops one sound early (stock does it too), which
    swallows the last word ("options" -> "option"). Each attempt is transcribed with `asr` (a faster_whisper
    WhisperModel; base.en is plenty); the first attempt whose last word matches the text and whose WER is
    <= max_wer wins, otherwise the attempt with the best (last-word, WER) score is returned.
    Returns (wav, info) where info = dict(attempts, last_word_ok, wer)."""
    import librosa, jiwer
    want = _norm_words(text)
    best = None
    for k in range(tries):
        torch.manual_seed(seed + k)
        wav = generate_clean(model, text, **kw)
        segs, _ = asr.transcribe(librosa.resample(wav, orig_sr=model.sr, target_sr=16000), language="en", beam_size=1)
        got = _norm_words(" ".join(s.text for s in segs))
        ok = bool(got) and got[-1] == want[-1]
        wer = jiwer.wer(" ".join(want), " ".join(got)) if got else 1.0
        score = (ok, -wer)
        if best is None or score > best[0]: best = (score, wav, dict(attempts=k + 1, last_word_ok=ok, wer=wer))
        if ok and wer <= max_wer: break
    return best[1], best[2]

def extend_pauses(wav, sr, factor=1.6, min_pause=0.12, max_added=0.35, quiet_db=-35):
    """Lengthen the natural pauses inside a chunk (stretches of >= min_pause below quiet_db re peak) by `factor`,
    adding at most max_added seconds each, by repeating the pause's own quiet audio (so the room tone stays
    continuous). Leading/trailing silence is untouched."""
    x = np.asarray(wav, dtype=np.float32); hop = int(sr * 0.01)
    if len(x) < hop * 10: return x
    env = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2)) for i in range(0, len(x) - hop + 1, hop)])
    q = 20 * np.log10(env / (env.max() + 1e-9) + 1e-12) < quiet_db
    loud = np.where(~q)[0]
    if len(loud) < 2: return x
    out, last = [], 0; i = loud[0]
    while i <= loud[-1]:
        if q[i]:
            j = i
            while j <= loud[-1] and q[j]: j += 1
            dur = (j - i) * hop / sr
            if dur >= min_pause:
                a, b = i * hop, j * hop; mid = (a + b) // 2
                add = int(min(dur * (factor - 1), max_added) * sr)
                pad = np.resize(x[a:b], add)  # tile the pause's own quiet audio
                n = min(int(sr * 0.005), len(pad) // 2)
                if n: pad[:n] *= np.linspace(0, 1, n); pad[-n:] *= np.linspace(1, 0, n)
                out += [x[last:mid], pad]; last = mid
            i = j
        else: i += 1
    out.append(x[last:])
    return np.concatenate(out)
