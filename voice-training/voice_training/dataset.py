"""Step `dataset`: kit-aligned training clips -> dataset/{wavs,metadata.csv,times.csv,split.csv,report.json}.

You read the kit's item numbers aloud ("one hundred fifty three. I should like to..."), so Whisper's word stream
is split at spoken item numbers into takes. Rules:
  * "lines" sessions (isolated sentences, project.json): each kit line is fuzzy-aligned (word level, ratio >= .85)
    to the word stream in order; a later window that matches as well is a retake and wins (last take kept); lines
    with a low-confidence decode are dropped. Long passages (> 40 words) are split into sentences first.
  * "items" sessions (paragraphs, unscripted): last take of each item; a spoken do-over ("let me do that over",
    "start over", "scratch that") cuts the take up to it; inside a take, a sentence whose first 4 words are
    repeated by a later sentence within 30 s is a derailed retake and is dropped; minor disfluencies stay.
    3-15 s clips plus 10-25 s merged clips (natural pauses kept). With 3-digit item numbers, a numeral in the
    session's range marks an item even mid-sentence (Whisper often runs it into the previous sentence).
  * the spoken number itself is never inside a clip; text before the first heard marker of an items session is the
    session's first item (from its first full sentence: Whisper tends to skip the spoken session title).
  * validation (~5 %): every lines-session line with N % val_every_nth_line == nth/2, plus val_items (or, if empty,
    one middle item from every other items session).
  * audio: 24 kHz (soxr), each clip at the same speech RMS (level_dbfs over voiced frames, peak <= -1 dBFS).
  * re-punctuation: clips whose text came back unpunctuated (< 3 marks per 100 words) are re-transcribed alone
    without a prompt and replaced when that agrees (WER <= 15 %) and is punctuated.
"""
import csv, collections, difflib, json, re
import numpy as np, librosa, soundfile as sf
from .common import CSV

SR = 24000
norm = lambda t: " ".join(re.sub(r"[^a-z0-9' ]", " ", t.lower()).split())
REDO = re.compile(r"(let me )?(just )?(do|say|read) (that|this|it)( one)? (over|again)|start (that )?over|scratch that", re.I)
GLUED = re.compile(r"^\s*(\d{1,3})[.,:]?([A-Za-z].*)$")
UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}

def parse_number(toks):
    """Longest spoken/digit number at the start of toks (list of word strings) -> (value, n_tokens) or None."""
    w0 = toks[0].strip().lower().rstrip(".,:;")
    if re.fullmatch(r"\d{1,3}", w0): return int(w0), 1
    val, cur, used, seen = 0, 0, 0, False
    for t in toks[:6]:
        parts = t.strip().lower().rstrip(".,:;").split("-")
        ok = True
        for q in parts:
            if q in UNITS: cur += UNITS[q]
            elif q in TENS: cur += TENS[q]
            elif q == "hundred" and seen: cur *= 100
            elif q in ("and", "a") and used: pass
            elif q == "a" and not used: cur = 1  # "a hundred"
            else: ok = False; break
            seen = True
        if not ok: break
        used += 1
        if t.strip()[-1:] in ".,:;": break
    return (val + cur, used) if seen and used else None

def takes(meta, lo, hi):
    """Split a recording's words into (item, [words]) takes at spoken item numbers in [lo, hi].
    A number counts as an item marker only after a pause (>= .25 s) or a sentence end, and only if it repeats the
    current item (a retake) or moves forward by at most 15 (Whisper sometimes misses a spoken number)."""
    ws = []
    for s in meta["segments"]:
        for k, w in enumerate(s["words"]): ws.append(dict(w, bad=s["avg_logprob"] < -0.6, seg_start=(k == 0)))
    out, cur, item, i = [], [], None, 0
    while i < len(ws):
        w = ws[i]; prev = ws[i - 1] if i else None
        boundary = prev is None or w["seg_start"] or w["start"] - prev["end"] >= 0.25 or prev["word"].strip()[-1:] in ".?!"
        # Whisper often runs the item number straight into the previous sentence ("... for them 312 xdr is"); a
        # 3-digit numeral in the session's item range is a marker wherever it falls
        boundary = boundary or (lo >= 100 and bool(re.fullmatch(r"\d{3}[.,:]?(?:[A-Za-z].*)?", w["word"].strip())))
        g = GLUED.match(w["word"]); pn = parse_number([x["word"] for x in ws[i:i + 6]]) if boundary else None
        n, used = (int(g.group(1)), 1) if (g and boundary) else (pn if pn else (None, 0))
        fwd = n is not None and lo <= n <= hi and (item is None and n <= lo + 15 or item is not None and 0 <= n - item <= 15)
        if fwd:
            if item is not None: out.append((item, cur))
            elif cur: out.append((None, cur))  # words before the first marker (session 1's two warm-up passages)
            item, cur = n, []
            if g: cur.append(dict(w, word=" " + g.group(2), glued=True))
            i += used; continue
        cur.append(w); i += 1
    if cur: out.append((item, cur))
    return out

def align_lines(ws, lines, thr=0.85):
    """Sessions 1-2: match kit lines in order against the word stream (fuzzy, word level). For each line, the
    best window after the pointer is found, then any later window that matches as well (a retake) wins.
    Returns [(line_id, [words])]; leading spoken numbers are trimmed off each window."""
    toks = [norm(w["word"]) for w in ws]; out, p = [], 0
    def best(line, lo, hi):
        L = len(line); b = (0, None, None)
        for st in range(lo, min(hi, len(toks))):
            for ln in range(max(1, L - 2), L + 4):
                r = difflib.SequenceMatcher(None, toks[st:st + ln], line, autojunk=False).ratio()
                if r > b[0]: b = (r, st, st + ln)
        return b
    for lid, text in lines:
        line = norm(text).split()
        if not line: continue
        r, a, e = best(line, p, p + 4 * len(line) + 40)
        if r < thr: continue
        while True:  # later retake of the same line?
            r2, a2, e2 = best(line, e, e + 2 * len(line) + 20)
            if r2 >= thr: r, a, e = r2, a2, e2
            else: break
        while a < e and parse_number([w["word"] for w in ws[a:a + 6]]) and toks[a] not in line[:1]: a += 1
        out.append((lid, ws[a:e])); p = e
    return out

def level(x, target_db, peak_db=-1.0):
    """Scale to target RMS over voiced frames (50 ms frames within 30 dB of the clip's loudest), cap the peak."""
    fr = librosa.feature.rms(y=x, frame_length=1200, hop_length=600)[0]
    v = fr[fr > fr.max() * 10 ** (-30 / 20)]
    g = 10 ** (target_db / 20) / (np.sqrt(np.mean(v ** 2)) + 1e-9)
    g = min(g, 10 ** (peak_db / 20) / (np.abs(x).max() + 1e-9))
    return (g * x).astype(np.float32)

def text_of(ws): return "".join(w["word"] for w in ws).strip()

def drop_retakes(ws):
    """Split into Whisper-sentences; drop a sentence whose first 4 words recur as a later sentence's opening <= 30 s on."""
    sents, cur = [], []
    for w in ws:
        cur.append(w)
        if w["word"].strip()[-1:] in ".?!": sents.append(cur); cur = []
    if cur: sents.append(cur)
    keep = []
    for i, s in enumerate(sents):
        head = norm(text_of(s)).split()[:4]
        redo = len(head) == 4 and any(norm(text_of(t)).split()[:4] == head and t[0]["start"] - s[0]["start"] <= 30
                                      for t in sents[i + 1:])
        keep.append(None if redo else s)
    out = []
    for s in keep: out += [None] if s is None else s
    return out

def clips(words, lo_s, hi_s, close_at, break_gap):
    res, cur = [], []
    def flush():
        if cur and cur[-1]["end"] - cur[0]["start"] >= lo_s: res.append(list(cur))
        cur.clear()
    for i, w in enumerate(words):
        if w is None or w.get("bad"): flush(); continue
        if cur and (w["start"] - cur[-1]["end"] > break_gap or w["end"] - cur[0]["start"] > hi_s): flush()
        cur.append(w)
        nxt = next((x for x in words[i + 1:i + 2] if x), None); dur = cur[-1]["end"] - cur[0]["start"]
        gap = (nxt["start"] - w["end"]) if nxt else 9
        if close_at(dur, gap, w): flush()
    flush(); return res



def auto_val_items(w, kit):
    ses = sorted({s for s, _ in kit.values() if w.session_kind(s) == "items"})
    out = []
    for s in ses[1::2] or ses[:1]:
        its = sorted(n for n, (k, _) in kit.items() if k == s); out.append(its[len(its) // 2])
    return set(out)

def run(w):
    kit = {n: (s, re.sub(r"^[^:]{0,120}\): ", "", t)) for n, (s, t) in w.kit().items()}  # strip "Title (author): " headers
    val_items = set(w.cfg["val_items"]) or auto_val_items(w, kit); nth = w.cfg["val_every_nth_line"]
    out = w.p("dataset"); (out / "wavs").mkdir(parents=True, exist_ok=True)
    rows, times, split, report = [], [], [], {}
    for p in sorted(w.p("transcripts").glob("s*.json")):
        meta = json.loads(p.read_text()); ses = meta["session"]; kind_s = w.session_kind(ses)
        items = sorted(n for n, (s, _) in kit.items() if s == ses)
        audio = librosa.load(str(w.p("audio", meta["file"])), sr=SR, mono=True, res_type="soxr_vhq")[0]
        r = collections.defaultdict(float); r["in_min"] = meta["duration"] / 60; out_clips = []
        if kind_s == "lines":
            ws = [dict(x, bad=sg["avg_logprob"] < -0.6) for sg in meta["segments"] for x in sg["words"]]
            lines = []
            for n in items:
                t = kit[n][1]
                if len(t.split()) > 40: lines += [(n, x) for x in re.split(r"(?<=[.?!])\s+", t) if len(x.split()) >= 4]
                else: lines.append((n, t))
            got = align_lines(ws, lines); r["lines in kit"] = len(lines); r["lines aligned"] = len(got)
            for n, c in got:
                if any(x.get("bad") for x in c): r["lines dropped: low-confidence decode"] += 1; continue
                out_clips.append((n, "s", c))
        else:
            last = {}
            for n, ws in takes(meta, items[0], items[-1]):
                if n is None:
                    k = next((j + 1 for j, x in enumerate(ws) if x["word"].strip()[-1:] in ".?!"), 0); n, ws = items[0], ws[k:]
                last.setdefault(n, []).append(ws)
            r["items_in_kit"] = len(items); r["items_heard"] = len(last); r["retakes"] = sum(len(v) - 1 for v in last.values())
            for n in sorted(last):
                ws = [x for x in last[n][-1] if not x.get("glued")]
                t = "".join(x["word"] for x in ws); m = REDO.search(t)
                if m: k = sum(1 for _ in re.finditer(r"\S+", t[:m.end()])); r["do-overs cut"] += 1; ws = ws[k:]
                ws = drop_retakes(ws)
                short = clips(ws, 3, 15, lambda d, g, x: d >= 3 and (g > 0.5 or (d >= 8 and g > 0.25)), 0.8)
                long_ = clips(ws, 10, 25, lambda d, g, x: (d >= 10 and x["word"].strip()[-1:] in ".?!" and g > 0.3) or (d >= 20 and g > 0.4), 2.0)
                out_clips += [(n, "s", c) for c in short] + [(n, "l", c) for c in long_]
        for k, (n, kind, c) in enumerate(out_clips):
            st = max(0, c[0]["start"] - 0.06); en = c[-1]["end"] + 0.15; x = audio[int(st * SR):int(en * SR)]
            if len(x) / SR < 1.5 or len(x) / SR > 30: continue
            fn = f"s{ses}_{n:03d}_{kind}{k:03d}.wav"; sf.write(out / "wavs" / fn, level(x, w.cfg["level_dbfs"]), SR, subtype="PCM_16")
            val = (kind_s == "lines" and n % nth == nth // 2) or (kind_s == "items" and n in val_items)
            rows.append((fn, text_of(c))); times.append((fn, f"s{ses}", f"{st:.2f}", f"{en:.2f}"))
            split.append((fn, "val" if val else "train", kind))
            r[("val " if val else "train ") + ("long" if kind == "l" else "short") + " min"] += (en - st) / 60
        report[f"session {ses}"] = {k: round(v, 1) for k, v in r.items()}; print(f"session {ses}", report[f"session {ses}"], flush=True)
    rows = repunctuate(w, rows)
    csv.writer(open(out / "metadata.csv", "w", newline="", encoding="utf-8"), **CSV).writerows(rows)
    csv.writer(open(out / "times.csv", "w", newline=""), **CSV).writerows(times)
    csv.writer(open(out / "split.csv", "w", newline=""), **CSV).writerows(split)
    report["_val_items"] = sorted(val_items); (out / "report.json").write_text(json.dumps(report, indent=1))
    tr = sum(v for k0, r in report.items() if not k0.startswith("_") for k, v in r.items() if k.startswith("train"))
    va = sum(v for k0, r in report.items() if not k0.startswith("_") for k, v in r.items() if k.startswith("val"))
    print(f"train {tr:.1f} min, val {va:.1f} min ({100 * va / (tr + va + 1e-9):.1f} %)")

def repunctuate(w, rows):
    import jiwer
    from faster_whisper import WhisperModel
    pr = lambda t: sum(t.count(x) for x in ".,?!") / max(1, len(t.split())); wm = None; log = {}
    n = lambda t: " ".join(re.sub(r"[^a-z0-9' ]", " ", t.lower().replace("-", " ")).split())
    for k, (f, t) in enumerate(rows):
        if len(t.split()) < 15 or pr(t) >= 0.03: continue
        wm = wm or WhisperModel(w.cfg["whisper_model"], device="cuda", compute_type="float16")
        segs, _ = wm.transcribe(librosa.load(str(w.p("dataset", "wavs", f)), sr=16000)[0], language="en", beam_size=5, condition_on_previous_text=False)
        new = " ".join(s.text.strip() for s in segs).strip(); e = jiwer.wer(n(t), n(new)); ok = pr(new) >= 0.03 and e <= 0.15
        log[f] = dict(old=t, new=new, wer=round(e, 3), used=ok)
        if ok: rows[k] = (f, new)
    w.p("dataset", "repunct.json").write_text(json.dumps(log, indent=1))
    print(f"re-punctuation: {sum(v['used'] for v in log.values())}/{len(log)} unpunctuated clips replaced")
    return rows
