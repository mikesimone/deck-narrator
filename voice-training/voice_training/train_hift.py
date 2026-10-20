"""Trainer behind step `train-hift`: fine-tune S3Gen's vocoder (HiFT: mel -> 24 kHz wav) on the speaker's full-band audio by
copy synthesis: real clip -> S3Gen's 80-bin 0-8 kHz mel -> HiFT -> compare with the real clip (the F0 predictor
stays stock). The stock HiFT has
to invent everything above 8 kHz from that mel; on the voice this was built for it came out 4 dB (8-10 kHz) to
12 dB (10-12 kHz) short of the real recordings. Recipe that worked: LR 2e-6, 3000 steps (gentle; kept the best
speaker similarity) - LR 1e-5 with --hf-weight 2 fits the spectrum closer but cost a little similarity.

No discriminators ship with Chatterbox, so this is a reconstruction-only fine-tune at a low LR from the GAN-trained
weights: multi-resolution STFT loss (spectral convergence + log-magnitude L1, 4 resolutions), a full-band log-mel L1
(128 bins, 0-12 kHz) and an extra log-magnitude L1 on the 8-12 kHz band. Random 64-frame (1.28 s) segments.
Every --eval-every steps it scores copy synthesis on the held-out clips: log-spectral distance per band (0-4, 4-8,
8-12 kHz) and band levels vs real, and saves the weights. Pick the step where 8-12 kHz improves without 0-8 kHz
getting worse."""
from voice_training.common import setup_platform; setup_platform()
import argparse, json, os, random, sys, time
import numpy as np, librosa, torch, torch.nn.functional as F
from librosa.filters import mel as mel_fn
from chatterbox.tts import ChatterboxTTS

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--wavs", required=True, help="dataset/wavs folder")
ap.add_argument("--out", required=True)
ap.add_argument("--steps", type=int, default=3000)
ap.add_argument("--lr", type=float, default=2e-6)
ap.add_argument("--batch", type=int, default=12)
ap.add_argument("--seg", type=int, default=64, help="mel frames per segment (480 samples each)")
ap.add_argument("--hf-weight", type=float, default=1.0)
ap.add_argument("--eval-every", type=int, default=500)
a = ap.parse_args(sys.argv[1:])
os.makedirs(a.out, exist_ok=True); torch.manual_seed(0); random.seed(0)
g = ChatterboxTTS.from_pretrained(device="cuda").s3gen; hift = g.mel2wav.train(); HOP = 480
items = torch.load(a.data)
def wav(i): return torch.from_numpy(librosa.load(os.path.join(a.wavs, i["file"]), sr=24000)[0])
train = [(i["mel"], wav(i)) for i in items if i["split"] == "train"]
val = [(i["mel"], wav(i)) for i in items if i["split"] == "val"]
print(f"{len(train)} train / {len(val)} val clips", flush=True)
for n, p in hift.f0_predictor.named_parameters(): p.requires_grad_(False)  # keep the stock F0 predictor: pitch stays put
params = [p for p in hift.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=a.lr, betas=(0.8, 0.99), weight_decay=0.0)
win = {n: torch.hann_window(n, device="cuda") for n in (256, 512, 1024, 2048)}
RES = [(256, 64), (512, 128), (1024, 256), (2048, 512)]
MB = torch.from_numpy(mel_fn(sr=24000, n_fft=1024, n_mels=128, fmin=0, fmax=12000)).float().cuda()

def mag(x, n, h): return torch.stft(x, n, h, n, window=win[n], return_complex=True).abs().clamp(min=1e-5)
def losses(y, x):
    sc = lm = 0.0
    for n, h in RES:
        Y, X = mag(y, n, h), mag(x, n, h)
        sc = sc + torch.norm(X - Y, p="fro") / torch.norm(X, p="fro"); lm = lm + F.l1_loss(Y.log(), X.log())
    Y, X = mag(y, 1024, 256), mag(x, 1024, 256)
    mel = F.l1_loss((MB @ Y).clamp(min=1e-5).log(), (MB @ X).clamp(min=1e-5).log())
    hf = F.l1_loss(Y[:, 341:].log(), X[:, 341:].log())  # bins >= 8 kHz (1024-pt FFT at 24 kHz: 23.4 Hz/bin)
    return sc / len(RES), lm / len(RES), mel, hf

def batch():
    mels, wavs = [], []
    for m, w in random.choices(train, k=a.batch):
        n = min(m.shape[1], len(w) // HOP)
        s = random.randint(0, max(0, n - a.seg)); L = min(a.seg, n)
        mm = F.pad(m[:, s:s + L], (0, a.seg - L)); ww = F.pad(w[s * HOP:(s + L) * HOP], (0, (a.seg - L) * HOP))
        mels.append(mm); wavs.append(ww)
    return torch.stack(mels).cuda(), torch.stack(wavs).cuda()

def bands_db(y):
    S = np.abs(librosa.stft(y, n_fft=1024)) ** 2; f = librosa.fft_frequencies(sr=24000, n_fft=1024)
    e = S.sum(0); S = S[:, e > np.percentile(e, 30)]; b = lambda lo, hi: S[(f >= lo) & (f < hi)].sum(); r = b(500, 2000)
    return [10 * np.log10(b(lo, hi) / r) for lo, hi in ((4000, 8000), (8000, 10000), (10000, 12000))]

@torch.no_grad()
def evaluate():
    hift.eval(); lsd = {k: [] for k in ("0-4k", "4-8k", "8-12k")}; lv = []; rv = []
    for m, w in val:
        n = min(m.shape[1], len(w) // HOP); y = hift.inference(m[None, :, :n].cuda())[0][0].cpu()
        x = w[:n * HOP]; L = min(len(x), len(y)); x, y = x[:L].numpy(), y[:L].numpy()
        X = np.log10(np.abs(librosa.stft(x, n_fft=1024)) ** 2 + 1e-9); Y = np.log10(np.abs(librosa.stft(y, n_fft=1024)) ** 2 + 1e-9)
        f = librosa.fft_frequencies(sr=24000, n_fft=1024); act = X.max(0) > X.max() - 6  # frames within 60 dB of the clip peak
        for k, (lo, hi) in zip(lsd, ((0, 4000), (4000, 8000), (8000, 12000))):
            sel = (f >= lo) & (f < hi); lsd[k].append(float(np.mean(np.sqrt(np.mean((10 * (X[sel][:, act] - Y[sel][:, act])) ** 2, 0)))))
        lv.append(bands_db(y)); rv.append(bands_db(x))
    hift.train()
    return dict(**{f"lsd_{k}": round(float(np.mean(v)), 3) for k, v in lsd.items()},
                bands_gen=[round(float(v), 1) for v in np.mean(lv, 0)], bands_real=[round(float(v), 1) for v in np.mean(rv, 0)])

log = [dict(step=0, **evaluate())]; print(log[-1], flush=True)
t0 = time.time(); run = np.zeros(4)
for step in range(1, a.steps + 1):
    m, x = batch()
    y, _ = hift({"speech_feat": m.transpose(1, 2)}, "cuda")
    L = min(y.shape[-1], x.shape[-1]); sc, lm, mel, hf = losses(y[:, :L].float(), x[:, :L])
    loss = sc + lm + mel + a.hf_weight * hf
    opt.zero_grad(set_to_none=True); loss.backward(); torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step()
    run += [sc.item(), lm.item(), mel.item(), hf.item()]
    if step % 100 == 0:
        print(f"step {step} sc {run[0]/100:.3f} logmag {run[1]/100:.3f} mel {run[2]/100:.3f} hf {run[3]/100:.3f} "
              f"peak {torch.cuda.max_memory_allocated()/2**30:.1f}G {time.time()-t0:.0f}s", flush=True); run[:] = 0
    if step % a.eval_every == 0:
        torch.save(hift.state_dict(), f"{a.out}/hift_s{step}.pt")
        log.append(dict(step=step, **evaluate())); print(log[-1], flush=True); json.dump(log, open(f"{a.out}/log.json", "w"), indent=1)
