"""Generation + scoring shared by the pick/sweep steps.
Gen: one ChatterboxTTS kept on the GPU; T3 / S3Gen flow / vocoder weights are swapped in from checkpoints.
Scorer: Whisper WER, ECAPA speaker similarity against the real held-out clip, prosody vs the real clip, and
brightness (share of energy above 4 kHz)."""
import os, re, time
import numpy as np, librosa, torch, torchaudio
from . import prosody, chatterbox_fix

TESTS = {
    "short": "Hi, and welcome. Today we're going to take a look at how this works.",
    "paragraph": ("Every good plan starts with a simple question: what are we actually trying to solve? Once we can "
                  "say that in one sentence, the rest gets easier. We gather what we know, test our first guess, and "
                  "keep going until the answer holds up."),
    "numbers": "Version 2.4 shipped on March 3rd with 37 fixes across 12 modules.",
}

class Gen:
    def __init__(self):
        from chatterbox.tts import ChatterboxTTS
        self.m = ChatterboxTTS.from_pretrained(device="cuda")
        cpu = lambda mod: {k: v.detach().to("cpu", copy=True) for k, v in mod.state_dict().items()}
        self.base_t3, self.base_flow, self.base_hift = cpu(self.m.t3), cpu(self.m.s3gen.flow), cpu(self.m.s3gen.mel2wav)

    def load(self, t3=None, flow=None, hift=None):
        """None = stock for each part."""
        sd = self.base_t3 if t3 is None else torch.load(t3, map_location="cuda")
        r = self.m.t3.load_state_dict({k: v.float() for k, v in sd.items()}, strict=False)  # after the first generate(), T3
        assert not r.unexpected_keys and all(k.startswith("patched_model.") for k in r.missing_keys), r  # has a patched_model alias
        self.m.s3gen.flow.load_state_dict(self.base_flow if flow is None else torch.load(flow, map_location="cuda"), strict=True)
        self.m.s3gen.mel2wav.load_state_dict(self.base_hift if hift is None else torch.load(hift, map_location="cuda"), strict=True)

    def t3_conds(self, wav, exaggeration):
        from chatterbox.models.s3tokenizer import S3_SR
        from chatterbox.models.t3.modules.cond_enc import T3Cond
        w16 = librosa.load(wav, sr=S3_SR)[0]
        tok, _ = self.m.s3gen.tokenizer.forward([w16[:self.m.ENC_COND_LEN]], max_len=self.m.t3.hp.speech_cond_prompt_len)
        ve = torch.from_numpy(self.m.ve.embeds_from_wavs([w16], sample_rate=S3_SR)).mean(0, keepdim=True)
        return T3Cond(speaker_emb=ve, cond_prompt_speech_tokens=torch.atleast_2d(tok), emotion_adv=exaggeration * torch.ones(1, 1, 1)).to(device=self.m.device)

    def run(self, jobs, outdir, ref_wav, exaggeration=0.5, cfg_weight=0.5, temperature=0.8, seed=42, t3_ref=None):
        """ref_wav conditions everything; with t3_ref, ref_wav only feeds S3Gen (timbre) and t3_ref feeds T3."""
        os.makedirs(outdir, exist_ok=True)
        self.m.prepare_conditionals(ref_wav, exaggeration=exaggeration)
        if t3_ref: self.m.conds.t3 = self.t3_conds(t3_ref, exaggeration)
        for k, (fn, text) in enumerate(jobs):
            torch.manual_seed(seed + k)
            w = chatterbox_fix.generate_clean(self.m, text, exaggeration=exaggeration, cfg_weight=cfg_weight, temperature=temperature)
            torchaudio.save(os.path.join(outdir, f"{fn}.wav"), torch.from_numpy(w)[None], self.m.sr)
        torch.cuda.empty_cache()

def hf_ratio(path, cut=4000):
    y, sr = librosa.load(path, sr=24000)
    S = np.abs(librosa.stft(y, n_fft=1024)) ** 2; f = librosa.fft_frequencies(sr=sr, n_fft=1024)
    return float(S[f >= cut].sum() / (S.sum() + 1e-12))

class Scorer:
    def __init__(self, w):
        from faster_whisper import WhisperModel
        from speechbrain.inference.speaker import EncoderClassifier
        self.real_dir = str(w.p("dataset", "wavs"))
        self.wm = WhisperModel(w.cfg["whisper_model"], device="cuda", compute_type="float16")
        self.enc = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cuda:0"}, savedir=str(w.p("ft", "ecapa")))
        self._real = {}

    def emb(self, p):
        e = self.enc.encode_batch(torch.tensor(librosa.load(p, sr=16000)[0])[None].cuda()).squeeze().cpu().numpy()
        return e / np.linalg.norm(e)

    @staticmethod
    def norm(s): return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.' ]", " ", s.lower().replace("-", " "))).replace(". ", " ").strip(" .")

    def score(self, outdir, jobs):
        import jiwer
        refs, hyps, sims, pairs, hf, hf_real = [], [], [], [], [], []
        for fn, text in jobs:
            p = os.path.join(outdir, f"{fn}.wav")
            segs, _ = self.wm.transcribe(librosa.load(p, sr=16000)[0], language="en", beam_size=5)
            refs.append(self.norm(text)); hyps.append(self.norm(" ".join(s.text for s in segs))); hf.append(hf_ratio(p))
            if fn.startswith("val_"):
                rp = os.path.join(self.real_dir, fn[4:] + ".wav")
                if rp not in self._real: self._real[rp] = (self.emb(rp), prosody.analyze(rp, text), hf_ratio(rp))
                e, pr, h = self._real[rp]; sims.append(float(self.emb(p) @ e)); pairs.append((pr, prosody.analyze(p, text))); hf_real.append(h)
        torch.cuda.empty_cache()
        out = dict(wer=jiwer.wer(refs, hyps), spk_sim=float(np.mean(sims)) if sims else float("nan"),
                   hf_ratio=float(np.mean(hf)), hf_real=float(np.mean(hf_real)) if hf_real else float("nan"))
        if pairs: out.update(prosody.summarize(pairs))
        return out
