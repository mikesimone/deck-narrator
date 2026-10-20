"""Step `features`: precompute training inputs from dataset/ (one model load, all sessions):
  ft/t3_tokens.pt   per clip: text tokens, S3 speech tokens (16 kHz, 25 Hz), voice-encoder embedding, session
                    ('rec' = 's<N>'), split, source times (so long clips never condition on audio overlapping them)
  ft/s3gen_feats.pt per clip: S3 speech tokens + the 24 kHz 80-bin log-mel S3Gen predicts (cropped to exactly 2x
                    the tokens) + the CAMPPlus x-vector: the fields CausalMaskedDiffWithXvec.compute_loss expects."""
import csv, collections, torch, librosa
from .common import CSV

def run(w):
    from chatterbox.tts import ChatterboxTTS, punc_norm
    from chatterbox.models.s3tokenizer import S3_SR
    from chatterbox.models.s3gen.const import S3GEN_SR
    m = ChatterboxTTS.from_pretrained(device="cuda"); g = m.s3gen; D = w.p("dataset")
    times = {f: (r, float(s), float(e)) for f, r, s, e in csv.reader(open(D / "times.csv"), **CSV)}
    split = {f: sp for f, sp, _ in csv.reader(open(D / "split.csv"), **CSV)}
    t3, s3 = [], []
    with torch.inference_mode():
        for f, text in csv.reader(open(D / "metadata.csv", encoding="utf-8"), **CSV):
            w16 = librosa.load(str(D / "wavs" / f), sr=S3_SR)[0]; w24 = librosa.load(str(D / "wavs" / f), sr=S3GEN_SR)[0]
            rec, st, en = times[f]; base = dict(file=f, rec=rec, text=text, split=split[f], start=st, end=en)
            tok, _ = g.tokenizer.forward([w16])
            t3.append(dict(base, text_tokens=m.tokenizer.text_to_tokens(punc_norm(text))[0].cpu(), speech_tokens=tok[0].cpu(),
                           ve=torch.from_numpy(m.ve.embeds_from_wavs([w16], sample_rate=S3_SR)).mean(0).cpu()))
            x16 = torch.from_numpy(w16).cuda()[None]; mel = g.mel_extractor(torch.from_numpy(w24).cuda()[None])[0]
            tok2, _ = g.tokenizer(x16); n = min(tok2.shape[1], mel.shape[1] // 2)
            s3.append(dict(base, speech_tokens=tok2[0, :n].cpu(), mel=mel[:, :2 * n].cpu(), xvec=g.speaker_encoder.inference(x16)[0].float().cpu()))
    torch.save(t3, w.p("ft", "t3_tokens.pt")); torch.save(s3, w.p("ft", "s3gen_feats.pt"))
    print(collections.Counter((i["rec"], i["split"]) for i in t3))
