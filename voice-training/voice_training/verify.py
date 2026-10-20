"""Step `verify`: load a voice pack the way Deck Narrator does, in a FRESH process (stock ChatterboxTTS, strict loads),
generate one test line next to the zip and Whisper it back.

Loading code (reference implementation):
    m = ChatterboxTTS.from_pretrained(device)
    m.t3.load_state_dict(safetensors.torch.load_file("t3.safetensors"), strict=True)
    v = json.load(open("voice.json"))
    if v.get("s3gen"):                                                                    # fine-tuned S3Gen, BEFORE
        m.s3gen.load_state_dict(safetensors.torch.load_file(v["s3gen"]), strict=True)     # prepare_conditionals
    timbre = v.get("timbre_reference")
    m.prepare_conditionals(timbre or "reference.wav", exaggeration=v["exaggeration"])   # S3Gen ref_dict (+ T3 conds)
    if timbre:                                                                            # split: T3 conds from reference.wav
        w16 = librosa.load("reference.wav", sr=S3_SR)[0]
        tok, _ = m.s3gen.tokenizer.forward([w16[:m.ENC_COND_LEN]], max_len=m.t3.hp.speech_cond_prompt_len)
        ve = torch.from_numpy(m.ve.embeds_from_wavs([w16], sample_rate=S3_SR)).mean(0, keepdim=True)
        m.conds.t3 = T3Cond(speaker_emb=ve, cond_prompt_speech_tokens=torch.atleast_2d(tok),
                            emotion_adv=v["exaggeration"] * torch.ones(1, 1, 1)).to(device=m.device)
    wav = chatterbox_fix.generate_clean(m, text, exaggeration=v["exaggeration"], cfg_weight=v["cfg_weight"],
                                        temperature=v["temperature"])
    if v.get("pause_scale"): wav = chatterbox_fix.extend_pauses(wav, m.sr, factor=v["pause_scale"])
    if v.get("speed"): wav = chatterbox_fix.time_stretch(wav, m.sr, v["speed"])
"""
import json, os, re, sys, tempfile, zipfile

def main(zp):
    import librosa, torch, jiwer, soundfile as sf
    from safetensors.torch import load_file
    from chatterbox.tts import ChatterboxTTS
    from chatterbox.models.s3tokenizer import S3_SR
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    from . import chatterbox_fix
    TEXT = "This is a test of my own voice in Deck Narrator."
    with tempfile.TemporaryDirectory() as d:
        zipfile.ZipFile(zp).extractall(d); print("contents", sorted(os.listdir(d)))
        v = json.load(open(f"{d}/voice.json")); print("voice.json", v)
        m = ChatterboxTTS.from_pretrained(device="cuda")
        sd = load_file(f"{d}/t3.safetensors"); print("t3 dtypes", {str(t.dtype) for t in sd.values()})
        print("t3 load_state_dict(strict=True):", m.t3.load_state_dict(sd, strict=True)); del sd
        if v.get("s3gen"):
            sg = load_file(f"{d}/{v['s3gen']}"); print("s3gen", len(sg), "tensors, dtypes", sorted({str(t.dtype) for t in sg.values()}))
            print("s3gen load_state_dict(strict=True):", m.s3gen.load_state_dict(sg, strict=True)); del sg
        timbre = v.get("timbre_reference")
        m.prepare_conditionals(f"{d}/{timbre}" if timbre else f"{d}/reference.wav", exaggeration=v["exaggeration"])
        if timbre:
            w16 = librosa.load(f"{d}/reference.wav", sr=S3_SR)[0]
            tok, _ = m.s3gen.tokenizer.forward([w16[:m.ENC_COND_LEN]], max_len=m.t3.hp.speech_cond_prompt_len)
            ve = torch.from_numpy(m.ve.embeds_from_wavs([w16], sample_rate=S3_SR)).mean(0, keepdim=True)
            m.conds.t3 = T3Cond(speaker_emb=ve, cond_prompt_speech_tokens=torch.atleast_2d(tok),
                                emotion_adv=v["exaggeration"] * torch.ones(1, 1, 1)).to(device=m.device)
        torch.manual_seed(0)
        wav = chatterbox_fix.generate_clean(m, TEXT, exaggeration=v["exaggeration"], cfg_weight=v["cfg_weight"], temperature=v["temperature"])
        if v.get("pause_scale"): wav = chatterbox_fix.extend_pauses(wav, m.sr, factor=v["pause_scale"])
        if v.get("speed"): wav = chatterbox_fix.time_stretch(wav, m.sr, v["speed"])
    out = zp[:-4] + "_test.wav"; sf.write(out, wav, m.sr); del m; torch.cuda.empty_cache()
    from faster_whisper import WhisperModel
    segs, _ = WhisperModel("large-v3", device="cuda", compute_type="float16").transcribe(librosa.load(out, sr=16000)[0], language="en")
    hyp = " ".join(s.text for s in segs).strip(); n = lambda s: re.sub(r"[^a-z0-9' ]", "", s.lower())
    print("output", out, "| whisper:", hyp, "| WER", jiwer.wer(n(TEXT), n(hyp)))
