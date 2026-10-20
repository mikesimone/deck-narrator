# Voice training (optional)

Train your own voice for Deck Narrator: record a reading kit, fine-tune Chatterbox on it, and get a voice
pack (`voice.zip`) that Deck Narrator loads. This folder is optional. Deck Narrator never imports it.

The pipeline fine-tunes three parts of Chatterbox (chatterbox-tts 0.1.7, the standard non-Turbo model):

| Part | What it learns | Trained on |
|---|---|---|
| **T3** (speech-token language model) | your rhythm, pacing and pauses | paragraph/unscripted sessions, plus the sentence sessions if their prosody matches |
| **S3Gen flow** (tokens to mel) | your timbre | every session |
| **S3Gen vocoder** (HiFT, mel to waveform) | your top end above 8 kHz, which the stock vocoder invents and usually dulls | every session |

## Requirements

- Windows 10/11 (native; no WSL) or Linux, Python 3.11 or 3.12
- An NVIDIA GPU with **12 GB+** VRAM and a recent driver. Peak use: T3 about 7.6 GB, S3Gen flow about 8.4 GB,
  vocoder about 6.7 GB, evaluation about 8 GB.
- About 30 GB of free disk (checkpoints) and about 90 minutes of clean recordings
- Training time on an RTX 5070-class card: minutes per model. The evaluation and settings sweep take the
  longest, a few hours in total.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

faster-whisper needs cuDNN and cuBLAS. `requirements.txt` installs them as `nvidia-*` wheels, and the pipeline
adds their DLL folders on Windows itself, so you don't need a CUDA toolkit. ffmpeg (used only for the
optional `speed` pace control) comes from the `imageio-ffmpeg` wheel if it isn't on PATH.

## 1. Build the reading kit

```powershell
python -m voice_training kit --work D:\voice --arctic cmuarctic.data --paragraphs my_paragraphs.txt --topics topics.txt
```

- `cmuarctic.data`: the CMU ARCTIC prompt list (festvox.org/cmu_arctic). About 300 prompts are picked for
  phone and diphone coverage, and become two sessions of isolated sentences ("lines" sessions).
- `my_paragraphs.txt`: about 60-70 minutes of material **in your own words**, such as past talk transcripts or
  posts, with paragraphs separated by blank lines and 1-2 minutes each. These become 14-minute "items" sessions.
  This is where T3 learns how you actually talk, so use material that sounds like you speaking, not like prose.
- `topics.txt` (optional): one prompt per line, about 90 seconds of unscripted speaking each.
- `--warmup a.txt b.txt` (optional): warm-up passages read at the start of session 1. Mind their licenses.

The command writes `kit/session-NN.txt` (teleprompter), `kit/kit.md` (print it) and `project.json`, which says
which sessions are `lines` and which are `items`. You can also write the kit by hand: items are numbered once
across the whole kit (`N. text`), one file per session.

## 2. Record

- **Room:** quiet and dead. A closet full of clothes beats a nice empty office. Turn off HVAC, fans and
  the fridge.
- **Mic:** 15-20 cm away, off-axis or behind a pop filter. Keep the same distance and gain every session.
  A phone recorder in uncompressed WAV is fine.
- **Format:** WAV, 44.1/48 kHz, 16/24-bit. Peaks around -12 to -6 dBFS, and nothing should clip.
- **No processing:** no noise suppression, compression, EQ or auto-gain.
- **One file per session**, 10-15 minutes long. Read the session title aloud first, then the number of every item
  before reading it. On a mistake, pause and re-read the item with its number; the last take wins. Saying
  "let me do that over" also works.
- **Paragraph sessions:** glance at the paragraph, then say it your way. Whisper transcribes what you actually
  said, so you don't have to stick to the script.
- **Sentence sessions:** read them in your normal rhythm, not as a list. They always train the timbre models. They
  train T3 only if their rhythm matches your talking rhythm (`compare` checks this) *and* that T3 still passes the
  new-text test in `pick-t3`. On the voice this was built for, adding them made T3 drop words, so it lost.

Put the WAVs in `D:\voice\raw\`. The file names don't matter; sessions are detected from the spoken title.

## 3. Train

```powershell
python -m voice_training all --work D:\voice
```

or one step at a time (`python -m voice_training <step> --work D:\voice`). Resume a failed run with
`all --from <step>`.

| Step | Output |
|---|---|
| `qc` | `qc.json`: duration, SNR, clipping, band limit and session per file, plus **flags**. A 70 Hz high-pass writes `audio/` |
| `transcribe` | `transcripts/`: Whisper large-v3, word timestamps |
| `dataset` | `dataset/`: 3-15 s and 10-25 s clips aligned to the kit (last clean take kept, false starts and derailed retakes dropped, minor disfluencies kept), about 5% held out for validation, 24 kHz, level-matched |
| `compare` | `ft/prosody_sessions.json`: lines vs items sessions on syllables/s, pauses/s and F0 range. If they're within 10%, the lines sessions train T3 too |
| `features` | `ft/t3_tokens.pt`, `ft/s3gen_feats.pt` |
| `refs` | `ft/refs.json`: 4 calm, typical 10-15 s reference clips from your paragraphs |
| `train-t3` | `ft/t3_items/` (and `ft/t3_all/`): 4 epochs, LR 2.5e-6, text loss at 0.1x |
| `pick-t3` | best run and epoch: must keep sentence-final words on 23 new sentences (98%+) with WER at most 4%, then WER at most 4% on held-out paragraphs, then the best speaker similarity |
| `train-s3gen` | `ft/s3gen/`: flow, 20 epochs, LR 2e-5 |
| `train-hift` | `ft/hift/`: vocoder, 3000 steps, LR 2e-6, reconstruction losses |
| `pick-s3gen` | flow epoch by speaker similarity; vocoder step: the brightest that keeps similarity within 0.01 of the stock vocoder |
| `sweep` | `ft/settings.json`: reference setups (single, or split T3/S3Gen) x exaggeration x cfg_weight, then a pace stage on cfg x exaggeration x temperature, ranked over pace, similarity, brightness, F0 range, pauses and WER at most 4% |
| `pack` | `out/voice.zip` |
| `verify` | loads the pack in a fresh process with strict loads, generates `out/voice_test.wav` and transcribes it back |

Check `qc.json` flags before training. SNR under 35 dB, a band limit under 12 kHz (MP3s, phone calls) or
clipping all cost quality you can't train back.

## The voice pack

A flat zip:

| File | |
|---|---|
| `reference.wav` | 24 kHz mono 16-bit. Conditions T3, and S3Gen too unless `timbre_reference.wav` is present |
| `timbre_reference.wav` | optional (split conditioning): conditions S3Gen only |
| `t3.safetensors` | plain `model.t3` state dict, bf16 |
| `s3gen.safetensors` | optional: the complete `model.s3gen` state dict (stock tokenizer and speaker encoder, plus the fine-tuned flow and vocoder), fp32 |
| `voice.json` | `exaggeration`, `cfg_weight`, `temperature`, plus optional `speed`, `pause_scale`, `timbre_reference`, `s3gen` |

The loading code is in `voice_training/verify.py` (docstring). Note that `s3gen.safetensors` loads with
`strict=True` *before* `prepare_conditionals`.

## Notes

- Everything a step writes lives in the work folder. Nothing goes anywhere else, and nothing is uploaded.
- `chatterbox_fix.py` is the same generation fix Deck Narrator uses: S3Gen silence tokens so the last
  phoneme decays, a fade-out, pause stretching and time stretching.
- The vocoder fine-tune has no discriminator (Chatterbox doesn't ship one), so it's deliberately gentle. If the
  result ever sounds buzzy, rerun `pick-s3gen` after deleting `ft/hift/`, which falls back to the stock vocoder.
