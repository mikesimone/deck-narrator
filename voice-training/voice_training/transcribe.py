"""Step `transcribe`: Whisper (large-v3) on audio/s<N>.wav with VAD and word timestamps -> transcripts/s<N>.json.
No conditioning on previous text (no hallucinated carry-over); the session's kit text is the initial prompt, so
jargon and punctuation follow the script."""
import json, re, librosa

def run(w):
    from faster_whisper import WhisperModel
    m = WhisperModel(w.cfg["whisper_model"], device="cuda", compute_type="float16")
    for src, q in sorted(w.load_json("qc.json").items(), key=lambda kv: kv[1]["session"]):
        k = q["session"]; out = w.p("transcripts", f"s{k}.json")
        if out.exists(): continue
        audio = librosa.load(q["out"], sr=16000, mono=True)[0]
        prompt = re.sub(r"^\d+\. ", "", w.kit_text(k), flags=re.M)[:600]
        segs, _ = m.transcribe(audio, language="en", word_timestamps=True, vad_filter=True, beam_size=5,
                               condition_on_previous_text=False, initial_prompt=prompt)
        rows = [dict(start=s.start, end=s.end, text=s.text.strip(), avg_logprob=s.avg_logprob,
                     words=[dict(start=x.start, end=x.end, word=x.word, prob=x.probability) for x in s.words or []]) for s in segs]
        out.write_text(json.dumps(dict(file=f"s{k}.wav", raw=src, session=k, duration=len(audio) / 16000, segments=rows), indent=1))
        print(src, "session", k, len(rows), "segments", flush=True)
