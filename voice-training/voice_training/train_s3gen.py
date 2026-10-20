"""Trainer behind step `train-s3gen`: fine-tune S3Gen's flow (token -> mel: conformer encoder + causal CFM decoder)
on ft/s3gen_feats.pt (all sessions; full-band audio). Recipe that worked: 20 epochs at 2e-5, micro 4 x accum 4,
pick by end-to-end speaker similarity (epoch ~10); peak VRAM ~8.4 GB. The S3 tokenizer, CAMPPlus speaker encoder and the HiFT vocoder (mel -> wav) stay stock:
the mel S3Gen predicts is 80 bins up to 8 kHz, and the vocoder fills in the band above it from that mel.

Loss is CosyVoice's own CausalMaskedDiffWithXvec.compute_loss (conditional flow matching on the target mel, the
utterance's x-vector as speaker embedding, a random 0-30 % prefix of the target as the mel prompt half the time,
20 % condition dropout for CFG). Val loss is computed with fixed seeds (same noise, timesteps and prompts every
epoch) and averaged over 3 passes, since the CFM loss is very noisy. Saves the fp32 flow state dict per epoch.
"""
from voice_training.common import setup_platform; setup_platform()
import argparse, json, math, os, random, sys, time
import torch, torch.nn.functional as F
from chatterbox.tts import ChatterboxTTS

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--epochs", type=int, default=20)
ap.add_argument("--lr", type=float, default=2e-5)
ap.add_argument("--micro", type=int, default=4)
ap.add_argument("--accum", type=int, default=4)
ap.add_argument("--warmup", type=int, default=50)
ap.add_argument("--freeze-encoder", action="store_true", help="train only the CFM decoder (estimator)")
a = ap.parse_args(sys.argv[1:])
os.makedirs(a.out, exist_ok=True)
torch.manual_seed(0); random.seed(0)

flow = ChatterboxTTS.from_pretrained(device="cpu").s3gen.flow.cuda().train()
if a.freeze_encoder:
    for n, p in flow.named_parameters():
        if not n.startswith("decoder."): p.requires_grad_(False)
params = [p for p in flow.parameters() if p.requires_grad]
print(f"trainable params {sum(p.numel() for p in params)/1e6:.1f}M", flush=True)
opt = torch.optim.AdamW(params, lr=a.lr, betas=(0.9, 0.98), weight_decay=0.01)

items = torch.load(a.data)
train = [i for i in items if i["split"] == "train"]; val = [i for i in items if i["split"] == "val"]
print(f"{len(train)} train / {len(val)} val clips", flush=True)

def collate(b):
    T = max(len(i["speech_tokens"]) for i in b)
    return dict(speech_token=torch.stack([F.pad(i["speech_tokens"], (0, T - len(i["speech_tokens"]))) for i in b]),
                speech_token_len=torch.tensor([len(i["speech_tokens"]) for i in b]),
                speech_feat=torch.stack([F.pad(i["mel"], (0, 2 * T - i["mel"].shape[1])) for i in b]),
                speech_feat_len=torch.tensor([i["mel"].shape[1] for i in b]),
                embedding=torch.stack([i["xvec"] for i in b]))

def step_loss(b):
    with torch.autocast("cuda", dtype=torch.bfloat16):
        return flow.compute_loss(collate(b), "cuda")["loss"]

@torch.no_grad()
def evaluate():
    st = (torch.get_rng_state(), torch.cuda.get_rng_state(), random.getstate())
    flow.eval(); tot = n = 0.0
    order = sorted(val, key=lambda i: i["file"])
    for k in range(3):
        torch.manual_seed(1000 + k); random.seed(1000 + k)
        for j in range(0, len(order), a.micro):
            b = order[j:j + a.micro]; tot += step_loss(b).item() * len(b); n += len(b)
    torch.set_rng_state(st[0]); torch.cuda.set_rng_state(st[1]); random.setstate(st[2])
    flow.train(); return tot / n

steps_per_epoch = math.ceil(len(train) / (a.micro * a.accum)); total = steps_per_epoch * a.epochs
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1, (s + 1) / a.warmup) *
                                          (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1, s / total)))))
log = [dict(epoch=0, val=evaluate())]; print(log[-1], flush=True)
torch.cuda.reset_peak_memory_stats(); rng = random.Random(0); step = 0; t0 = time.time()
for ep in range(1, a.epochs + 1):
    order = train[:]; rng.shuffle(order)
    order.sort(key=lambda i: len(i["speech_tokens"]) // 50 + rng.random())  # loose length buckets, then shuffle them
    chunks = [order[k:k + a.micro] for k in range(0, len(order), a.micro)]; rng.shuffle(chunks)
    run = 0.0
    for c, mb in enumerate(chunks):
        loss = step_loss(mb); (loss / a.accum).backward(); run += loss.item()
        if (c + 1) % a.accum == 0 or c == len(chunks) - 1:
            torch.nn.utils.clip_grad_norm_(params, 1.0); opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
            if step % 20 == 0:
                print(f"ep {ep} step {step}/{total} train {run / (c + 1):.4f} lr {sched.get_last_lr()[0]:.2e} "
                      f"peak {torch.cuda.max_memory_allocated() / 2**30:.1f}G", flush=True)
    torch.save(flow.state_dict(), f"{a.out}/flow_e{ep}.pt")
    log.append(dict(epoch=ep, val=evaluate(), train=run / len(chunks), step=step, elapsed_min=(time.time() - t0) / 60,
                    peak_vram_gib=torch.cuda.max_memory_allocated() / 2**30)); print(log[-1], flush=True)
    json.dump(log, open(f"{a.out}/log.json", "w"), indent=1)
