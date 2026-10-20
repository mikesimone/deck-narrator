"""Shared paths, project config and platform setup for the voice-training pipeline.

A *work folder* holds everything for one voice (nothing here writes anywhere else):
    project.json          sessions, validation picks, options (see README)
    kit/session-NN.txt    teleprompter files: numbered items "N. text", numbered once across the whole kit
    raw/*.wav             the recordings, one file per session (any names; the session is detected)
    audio/ transcripts/ dataset/ ft/ out/   created by the steps
"""
import json, os, re, sys, glob
from pathlib import Path

DEFAULTS = {
    "sessions": {},             # "1": "lines" (isolated sentences, aligned by text) | "items" (paragraphs/unscripted)
    "highpass_hz": 70,
    "val_every_nth_line": 20,   # lines sessions: line N is validation when N % 20 == 10
    "val_items": [],            # items sessions: item numbers held out (talk paragraphs); [] = pick ~5 % automatically
    "t3_lines_sessions": "auto",  # "auto" = include lines sessions in T3 if their prosody is within 10 % of items sessions
    "level_dbfs": -24.0,
    "whisper_model": "large-v3",
}

def setup_platform():
    """On Windows, make the CUDA DLLs from the pip nvidia-* wheels visible to ctranslate2 (faster-whisper)."""
    if sys.platform == "win32":
        import site
        for sp in site.getsitepackages() + [site.getusersitepackages()]:
            for sub in ("cudnn", "cublas", "cuda_runtime", "cuda_nvrtc"):
                d = Path(sp) / "nvidia" / sub / "bin"
                if d.is_dir():
                    os.add_dll_directory(str(d)); os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]

class Work:
    def __init__(self, root):
        self.root = Path(root).resolve()
        cfg = self.root / "project.json"
        self.cfg = dict(DEFAULTS, **(json.loads(cfg.read_text()) if cfg.exists() else {}))
        for d in ("audio", "transcripts", "dataset", "ft", "out"): (self.root / d).mkdir(exist_ok=True)

    def p(self, *parts): return self.root.joinpath(*parts)

    def session_kind(self, s): return self.cfg["sessions"].get(str(s), "items")

    def kit(self):
        """item number -> (session, text). Session files: kit/session-NN.txt."""
        out = {}
        for f in sorted(glob.glob(str(self.p("kit", "session-*.txt")))):
            s = int(re.search(r"session-(\d+)", f).group(1))
            for m in re.finditer(r"^(\d+)\. (.*)$", Path(f).read_text(encoding="utf-8"), re.M): out[int(m.group(1))] = (s, m.group(2))
        if not out: sys.exit(f"no kit found in {self.p('kit')} (session-NN.txt files with numbered lines)")
        return out

    def kit_text(self, s): return self.p("kit", f"session-{s:02d}.txt").read_text(encoding="utf-8")

    def save_json(self, name, obj): self.p(name).write_text(json.dumps(obj, indent=1))
    def load_json(self, name): return json.loads(self.p(name).read_text())

CSV = dict(delimiter="|", quoting=3, escapechar="\\")  # csv.QUOTE_NONE
