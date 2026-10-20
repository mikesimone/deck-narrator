"""Step `qc`: check every raw/*.wav and clean it.
Per file: format, duration, channel correlation, peak/RMS, noise floor and SNR (5th/90th percentile 50 ms frame
RMS), clipping (full-scale samples, longest run), usable band (highest frequency where loud frames sit >= 10 dB
over the quietest), energy share below 100 Hz, and which kit session it is (the spoken session title if you read
it aloud, else a fuzzy match of the first 90 s against the kit). Then mono mixdown + 4th-order zero-phase
Butterworth high-pass (project.json highpass_hz, default 70 Hz) -> audio/s<N>.wav. Report -> qc.json, with flags."""
import difflib, glob, json, os, re
import numpy as np, soundfile as sf, librosa
from scipy.signal import butter, sosfiltfilt

NUMS = "one two three four five six seven eight nine ten".split()

def stats(y, sr):
    hop = int(.025 * sr); fr = librosa.feature.rms(y=y, frame_length=int(.05 * sr), hop_length=hop)[0]
    floor, speech = np.percentile(fr, 5), np.percentile(fr, 90)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop)) ** 2; fq = librosa.fft_frequencies(sr=sr, n_fft=2048)
    n = min(S.shape[1], len(fr)); S, e = S[:, :n], fr[:n]
    loud = S[:, e >= np.percentile(e, 80)].mean(1); quiet = S[:, e <= np.percentile(e, 10)].mean(1)
    ok = np.where((10 * np.log10(loud / (quiet + 1e-20) + 1e-20) >= 10) & (fq > 1000))[0]
    return dict(peak_dbfs=round(20 * np.log10(np.abs(y).max() + 1e-9), 1), rms_dbfs=round(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9), 1),
                floor_dbfs=round(20 * np.log10(floor + 1e-9), 1), snr_db=round(20 * np.log10(speech / (floor + 1e-12)), 1),
                content_hz=round(float(fq[ok.max()])) if len(ok) else 0,
                sub100_share_db=round(float(10 * np.log10(S[fq < 100].sum() / (S.sum() + 1e-20))), 1))

def run(w):
    from faster_whisper import WhisperModel
    wm = WhisperModel(w.cfg["whisper_model"], device="cuda", compute_type="float16")
    kit = w.kit(); norm = lambda t: re.sub(r"[^a-z0-9' ]", " ", t.lower())
    out = {}
    for p in sorted(glob.glob(str(w.p("raw", "*.wav")))):
        x, sr = sf.read(p, dtype="float32", always_2d=True)
        corr = float(np.corrcoef(x[::50, 0], x[::50, 1])[0, 1]) if x.shape[1] == 2 else 1.0
        fs = np.abs(x).max(1) >= 32766 / 32768; d = np.diff(np.r_[0, fs.astype(np.int8), 0])
        run_ = int((np.where(d == -1)[0] - np.where(d == 1)[0]).max()) if fs.any() else 0
        y = x.mean(1)
        r = dict(sr=sr, ch=x.shape[1], dur_min=round(len(y) / sr / 60, 2), lr_corr=round(corr, 4), clip_samples=int(fs.sum()), clip_longest_run=run_, **stats(y, sr))
        segs, _ = wm.transcribe(librosa.resample(y[:int(90 * sr)], orig_sr=sr, target_sr=16000), language="en")
        head = norm(" ".join(s.text for s in segs))
        m = re.search(r"session (\d+|" + "|".join(NUMS) + r")\b", head)
        spoken = None if not m else (int(m.group(1)) if m.group(1).isdigit() else NUMS.index(m.group(1)) + 1)
        fuzzy = max(kit.items(), key=lambda kv: difflib.SequenceMatcher(None, head[:300], norm(kv[1][1])[:300]).ratio())[1][0]
        r.update(session=spoken or fuzzy, session_from="spoken title" if spoken else "fuzzy match", head=head[:160])
        flags = []
        if sr < 44100: flags.append(f"sample rate {sr} < 44.1 kHz")
        if r["snr_db"] < 35: flags.append(f"SNR {r['snr_db']} dB < 35")
        if run_ > 3: flags.append(f"clipping: run of {run_} full-scale samples")
        if r["content_hz"] < 12000: flags.append(f"band-limited: content to {r['content_hz']} Hz")
        r["flags"] = flags
        yh = sosfiltfilt(butter(4, w.cfg["highpass_hz"], btype="highpass", fs=sr, output="sos"), y).astype(np.float32)
        dst = w.p("audio", f"s{r['session']}.wav")
        if any(o["out"] == str(dst) for o in out.values()): raise SystemExit(f"{p}: two recordings map to session {r['session']}")
        r["out"] = str(dst); sf.write(dst, yh, sr, subtype="FLOAT")
        out[os.path.basename(p)] = r
        print(os.path.basename(p), "-> session", r["session"], f"| {r['dur_min']} min, SNR {r['snr_db']} dB, band {r['content_hz']} Hz",
              "| FLAGS: " + "; ".join(flags) if flags else "| ok", flush=True)
    w.save_json("qc.json", out)
