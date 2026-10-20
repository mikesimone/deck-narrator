"""Step `pack`: build the Deck Narrator voice pack -> out/voice.zip (flat zip):
  reference.wav          24 kHz mono 16-bit; conditions T3 (and S3Gen too unless timbre_reference.wav is present)
  timbre_reference.wav   optional (split conditioning): conditions S3Gen only
  t3.safetensors         plain model.t3 state dict, bf16 (load_state_dict casts into the fp32 params)
  s3gen.safetensors      optional: the COMPLETE model.s3gen state dict (stock tokenizer and speaker encoder + the
                         fine-tuned flow and vocoder), fp32; voice.json then has "s3gen": "s3gen.safetensors"
  voice.json             exaggeration, cfg_weight, temperature [, speed, pause_scale, timbre_reference, s3gen]
Uses ft/pick.json (checkpoints) and ft/settings.json (sweep winner)."""
import json, os, tempfile, zipfile
import librosa, soundfile as sf, torch
from safetensors.torch import save_file

def run(w, out=None):
    pk, st = w.load_json("ft/pick.json"), w.load_json("ft/settings.json"); out = out or str(w.p("out", "voice.zip"))
    wav = lambda src, dst: sf.write(dst, librosa.load(src, sr=24000, mono=True)[0], 24000, subtype="PCM_16")
    with tempfile.TemporaryDirectory() as d:
        save_file({k: v.to(torch.bfloat16).contiguous() for k, v in torch.load(pk["t3"], map_location="cpu").items()}, f"{d}/t3.safetensors")
        v = {"exaggeration": st["exaggeration"], "cfg_weight": st["cfg_weight"], "temperature": st["temperature"]}
        if st.get("speed"): v["speed"] = st["speed"]
        if st.get("pause_scale"): v["pause_scale"] = st["pause_scale"]
        files = ["reference.wav", "t3.safetensors", "voice.json"]
        if st.get("t3_ref"):
            wav(st["t3_ref"], f"{d}/reference.wav"); wav(st["gen_ref"], f"{d}/timbre_reference.wav")
            v["timbre_reference"] = "timbre_reference.wav"; files.append("timbre_reference.wav")
        else: wav(st["gen_ref"], f"{d}/reference.wav")
        if pk.get("flow") or pk.get("hift"):
            from chatterbox.tts import ChatterboxTTS
            g = ChatterboxTTS.from_pretrained(device="cpu").s3gen
            if pk.get("flow"): g.flow.load_state_dict(torch.load(pk["flow"], map_location="cpu"), strict=True)
            if pk.get("hift"): g.mel2wav.load_state_dict(torch.load(pk["hift"], map_location="cpu"), strict=True)
            save_file({k: t.contiguous() for k, t in g.state_dict().items()}, f"{d}/s3gen.safetensors")
            v["s3gen"] = "s3gen.safetensors"; files.append("s3gen.safetensors")
        json.dump(v, open(f"{d}/voice.json", "w"))
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files: z.write(f"{d}/{f}", f)
    print(out, round(os.path.getsize(out) / 2**20, 1), "MiB", v)
