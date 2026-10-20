"""Trainer behind step `train-t3`: fine-tune Chatterbox's T3 (speech-token LM) on ft/t3_tokens.pt. S3Gen, the S3
tokenizer and the voice encoder are never loaded here: their outputs were precomputed by step `features`.
Recipe that worked: full fine-tune from stock, LR 2.5e-6, text CE at 0.1x, 4 epochs, paragraph/unscripted sessions
only. Faster (5e-6) or with isolated-sentence sessions mixed in, later epochs start swallowing sentence-final and
rarer words on NEW text even while val loss still improves; `pick-t3` tests for exactly that;
peak VRAM ~7.6 GB (bf16 autocast, gradient checkpointing, 8-bit AdamW).

Loss is next-token CE on text and speech (the shipped T3.loss() compares logits at position i with token i,
which doesn't match inference, so it is reimplemented with the shift). Each sample is packed as
[cond | BOT text EOT | BOS speech EOS] contiguously and right-padded, matching the inference layout.
Conditioning (voice-encoder embedding + 6 s prompt tokens) comes from a *different* clip of the same
recording, so the model learns the voice rather than copying the prompt.
"""
from voice_training.common import setup_platform; setup_platform()
import argparse, json, math, os, random, sys, time
import torch, torch.nn.functional as F
from chatterbox.tts import ChatterboxTTS
from chatterbox.models.t3.modules.cond_enc import T3Cond

ap = argparse.ArgumentParser()
ap.add_argument("--epochs", type=int, default=4)
ap.add_argument("--lr", type=float, default=2.5e-6)
ap.add_argument("--micro", type=int, default=4)
ap.add_argument("--accum", type=int, default=4)
ap.add_argument("--warmup", type=int, default=30)
ap.add_argument("--out", required=True)
ap.add_argument("--tokens", required=True)
ap.add_argument("--text-weight", type=float, default=0.1)
ap.add_argument("--recs", help="comma-separated recordings (item['rec']) to train on, e.g. s3,s4,s5,s6,s7")
ap.add_argument("--val-recs", help="recordings to validate on (default: --recs), so runs on different sessions share a val set")
a = ap.parse_args(sys.argv[1:])
os.makedirs(a.out, exist_ok=True)
torch.manual_seed(0); random.seed(0)

t3 = ChatterboxTTS.from_pretrained(device="cpu").t3  # fp32 master weights
hp = t3.hp
t3 = t3.cuda().train()
t3.tfmr.config.use_cache = False
t3.tfmr.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
params = [p for p in t3.parameters() if p.requires_grad]
print(f"trainable params {sum(p.numel() for p in params)/1e6:.1f}M", flush=True)

import bitsandbytes as bnb
opt = bnb.optim.AdamW8bit(params, lr=a.lr, betas=(0.9, 0.98), weight_decay=0.01)

items = torch.load(a.tokens)
if a.recs:
    vr = (a.val_recs or a.recs).split(",")
    items = [i for i in items if i["rec"] in a.recs.split(",") or (i["split"] == "val" and i["rec"] in vr)]
    items = [i for i in items if i["split"] == "train" or i["rec"] in vr]
train = [i for i in items if i["split"] == "train"]
val = [i for i in items if i["split"] == "val"]
prompts = {}  # rec -> train clips long enough (>= 6 s = 150 tokens) to serve as conditioning
for i in train:
    if len(i["speech_tokens"]) >= hp.speech_cond_prompt_len: prompts.setdefault(i["rec"], []).append(i)
for rec in {i["rec"] for i in items}:
    prompts.setdefault(rec, [max((i for i in train if i["rec"] == rec), key=lambda i: len(i["speech_tokens"]))])

def pick_prompt(it, rng):
    # never condition on the target itself, or (v2: long clips contain short ones) on audio overlapping it
    def overlaps(p):
        return "start" in it and "start" in p and p["start"] < it["end"] and p["end"] > it["start"]
    c = [p for p in prompts[it["rec"]] if p["file"] != it["file"] and not overlaps(p)] or prompts[it["rec"]]
    return rng.choice(c)

def batch_loss(batch, rng):
    seqs, spans = [], []
    for it in batch:
        p = pick_prompt(it, rng)
        cond = T3Cond(speaker_emb=p["ve"][None].cuda(),
                      cond_prompt_speech_tokens=p["speech_tokens"][None, :hp.speech_cond_prompt_len].cuda(),
                      emotion_adv=0.5 * torch.ones(1, 1, 1, device="cuda"))
        ce = t3.prepare_conditioning(cond)[0]
        tt = torch.cat([torch.tensor([hp.start_text_token]), it["text_tokens"], torch.tensor([hp.stop_text_token])]).cuda()
        st = torch.cat([torch.tensor([hp.start_speech_token]), it["speech_tokens"], torch.tensor([hp.stop_speech_token])]).cuda()
        te = t3.text_emb(tt) + t3.text_pos_emb(tt[None])
        se = t3.speech_emb(st) + t3.speech_pos_emb(st[None])
        seqs.append(torch.cat([ce, te, se]))
        spans.append((len(ce), tt, st))
    L = max(len(s) for s in seqs)
    emb = torch.stack([F.pad(s, (0, 0, 0, L - len(s))) for s in seqs])
    mask = torch.stack([torch.arange(L, device="cuda") < len(s) for s in seqs]).long()
    h = t3.tfmr(inputs_embeds=emb, attention_mask=mask, use_cache=False).last_hidden_state
    lt = ls = 0.0; nt = ns = 0
    for b, (lc, tt, st) in enumerate(spans):
        th = h[b, lc:lc + len(tt) - 1]                       # predicts tt[1:]
        sh = h[b, lc + len(tt):lc + len(tt) + len(st) - 1]   # predicts st[1:]
        wt = 1.0
        lt = lt + wt * F.cross_entropy(t3.text_head(th).float(), tt[1:], reduction="sum"); nt += wt * (len(tt) - 1)
        ls = ls + wt * F.cross_entropy(t3.speech_head(sh).float(), st[1:], reduction="sum"); ns += wt * (len(st) - 1)
    return lt / nt, ls / ns

@torch.no_grad()
def evaluate():
    t3.eval(); rng = random.Random(1234); tl = sl = 0.0; n = 0
    for k in range(0, len(val), a.micro):
        with torch.autocast("cuda", dtype=torch.bfloat16):
            lt, ls = batch_loss(val[k:k + a.micro], rng)
        tl += lt.item(); sl += ls.item(); n += 1
    t3.train(); return tl / n, sl / n

steps_per_epoch = math.ceil(len(train) / (a.micro * a.accum))
total = steps_per_epoch * a.epochs
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1, (s + 1) / a.warmup) *
                                          (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1, s / total)))))
log = []
vt, vs = evaluate()
log.append(dict(epoch=0, val_text=vt, val_speech=vs)); print(log[-1], flush=True)
torch.cuda.reset_peak_memory_stats()
rng = random.Random(0); step = 0; t0 = time.time()
for ep in range(1, a.epochs + 1):
    order = train[:]; rng.shuffle(order)
    order.sort(key=lambda i: len(i["speech_tokens"]) // 50 + rng.random())  # loose length bucketing...
    chunks = [order[k:k + a.micro] for k in range(0, len(order), a.micro)]; rng.shuffle(chunks)  # ...then shuffle buckets
    run = 0.0
    for c, mb in enumerate(chunks):
        with torch.autocast("cuda", dtype=torch.bfloat16):
            lt, ls = batch_loss(mb, rng)
        ((a.text_weight * lt + ls) / a.accum).backward(); run += ls.item()
        if (c + 1) % a.accum == 0 or c == len(chunks) - 1:
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
            if step % 10 == 0:
                print(f"ep {ep} step {step}/{total} train_speech {run / (c + 1):.3f} lr {sched.get_last_lr()[0]:.2e} "
                      f"peak {torch.cuda.max_memory_allocated() / 2**30:.1f}G", flush=True)
    vt, vs = evaluate()
    sd = {k: v.to(torch.bfloat16) for k, v in t3.state_dict().items()}
    torch.save(sd, f"{a.out}/t3_e{ep}.pt")
    log.append(dict(epoch=ep, val_text=vt, val_speech=vs, train_speech=run / len(chunks), step=step,
                    elapsed_min=(time.time() - t0) / 60, peak_vram_gib=torch.cuda.max_memory_allocated() / 2**30))
    print(log[-1], flush=True)
    json.dump(log, open(f"{a.out}/log.json", "w"), indent=1)
