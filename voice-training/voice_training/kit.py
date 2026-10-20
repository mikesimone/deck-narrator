"""Step `kit`: build the reading kit -> kit/session-NN.txt (teleprompter), kit/kit.md (printable), project.json.

  python -m voice_training kit --work D:\\voice --arctic cmuarctic.data --paragraphs my_paragraphs.txt
                               [--topics topics.txt] [--warmup passage1.txt passage2.txt] [--n-arctic 300]

  --arctic      CMU ARCTIC prompt list (cmuarctic.data from festvox.org/cmu_arctic); --n-arctic of them are picked
                greedily for phone + diphone coverage (cmudict) -> two "lines" sessions (isolated sentences).
  --warmup      optional public-domain / licensed passages read at the start of session 1 (split into sentences).
  --paragraphs  your own material in your own words (talk transcripts, blog posts...), paragraphs separated by
                blank lines, 1-2 minutes each; about 60-70 minutes total -> ~14-minute "items" sessions.
  --topics      optional, one prompt per line: ~90 s of unscripted speaking each -> a final "items" session.
Items are numbered once across the whole kit, so "item 123" is unambiguous; read the number aloud before each item
and the session title at the start of each recording.
"""
import argparse, json, re, sys
WPM, SESSION_WORDS = 150, 14 * 150

def main(w, argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--arctic", required=True); ap.add_argument("--paragraphs", required=True)
    ap.add_argument("--topics"); ap.add_argument("--warmup", nargs="*", default=[]); ap.add_argument("--n-arctic", type=int, default=300)
    a = ap.parse_args(argv)
    import cmudict
    D = cmudict.dict()
    def phones(t):
        out = ["sil"]
        for x in re.findall(r"[a-z']+", t.lower()):
            if x in D: out += [re.sub(r"\d", "", p) for p in D[x][0]]
        return out + ["sil"]
    arctic = re.findall(r'\( (arctic_\w+) "(.*)" \)', open(a.arctic, encoding="utf-8").read())
    units = [set(zip(p, p[1:])) | set(p) for p in (phones(t) for _, t in arctic)]
    chosen, covered = [], set()
    for _ in range(min(a.n_arctic, len(arctic))):
        i = max((i for i in range(len(arctic)) if i not in chosen), key=lambda i: (len(units[i] - covered), -len(arctic[i][1])))
        chosen.append(i); covered |= units[i]
    sel = [arctic[i][1] for i in sorted(chosen)]; half = len(sel) // 2
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", open(a.paragraphs, encoding="utf-8").read()) if p.strip()]
    topics = [t.strip() for t in open(a.topics, encoding="utf-8")] if a.topics else []
    warm = [open(p, encoding="utf-8").read().strip() for p in a.warmup]
    sessions = [("Warm-up and sound coverage (part 1)", "lines", warm + sel[:half]), ("Sound coverage (part 2)", "lines", sel[half:])]
    cur, n, k = [], 0, 0
    for p in paras:
        cur.append(p); n += len(p.split())
        if n >= SESSION_WORDS: k += 1; sessions.append((f"Your material, part {k}", "items", cur)); cur, n = [], 0
    if cur: k += 1; sessions.append((f"Your material, part {k}", "items", cur))
    if topics: sessions.append(("Unscripted (about 90 seconds each, no script)", "items", [t for t in topics if t]))
    w.p("kit").mkdir(exist_ok=True); num = 0; md = ["# Voice recording kit", ""]; cfg = w.cfg.copy(); cfg["sessions"] = {}
    for s, (title, kind, items) in enumerate(sessions, 1):
        body = [f"Session {s} - {title}", ""]; md += [f"## Session {s} - {title}", ""]
        for t in items: num += 1; body.append(f"{num}. {t}\n"); md += [f"{num}. {t}", ""]
        w.p("kit", f"session-{s:02d}.txt").write_text("\n".join(body), encoding="utf-8"); cfg["sessions"][str(s)] = kind
        mins = 15 if title.startswith("Unscripted") else round(sum(len(t.split()) for t in items) / WPM, 1)
        print(f"session {s}: {kind}, {len(items)} items, ~{mins} min")
    w.p("kit", "kit.md").write_text("\n".join(md), encoding="utf-8")
    w.p("project.json").write_text(json.dumps({k: cfg[k] for k in cfg}, indent=1))
    print(f"ARCTIC: {len(sel)} prompts cover {len(covered)}/{len(set().union(*units))} phones+diphones")
