#!/usr/bin/env python3
"""deck-narrator GUI: a window over the command-line tool.

Every option the CLI has is a control here. The window builds the same command
line you would type and runs it as a separate process (deck-narrator.exe next
to this program in the Windows build, narrate.py from source), streaming its
output into the log pane. So the GUI can't drift from the CLI: it has no
rendering code of its own.

Run:  deck-narrator-gui            (Linux, after setup.sh)
      deck-narrator-gui.cmd        (Windows from source)
      Deck Narrator in the Start menu (Windows installer)
"""

import json
import os
import queue
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import narrate

IS_WINDOWS = os.name == "nt"
HERE = Path(__file__).resolve().parent
FROZEN = getattr(sys, "frozen", False)
TITLE = "Deck Narrator"
DICT_TEMPLATE = """\
# deck-narrator pronunciation dictionary
# One rule per line: word=what to say instead. Whole words, case-sensitive.
# Lines starting with # are comments. Inline fixes in the notes, like
# [present](/pɹizˈɛnt/), beat this file. Full guide: docs/PRONUNCIATION.md
#
# Examples:
# NGINX=engine x
# SQL=sequel
# Kubernetes=koo ber net eez
"""

# Every CLI option, and the control that sets it. test/test_gui.py checks this
# against narrate.build_parser(), so a new CLI option fails the tests until the
# GUI has it. "help"/"version" are argparse's own.
COVERED = {
    "deck", "output", "voice", "list_voices", "speed", "pad", "empty_duration",
    "skip_empty", "slides", "no_builds", "build_hold", "show_builds",
    "pronunciations", "device", "show_phonemes", "phonemes", "sample", "keep_temp",
    "help", "version",
}


def cli_command():
    """The command that runs the CLI: the sibling .exe when frozen, else narrate.py."""
    if FROZEN:
        exe = Path(sys.executable).with_name("deck-narrator.exe" if IS_WINDOWS else "deck-narrator")
        return [str(exe)]
    py = Path(sys.executable)
    if py.name.lower() == "pythonw.exe":          # the GUI may run windowless; the CLI needs a console Python
        py = py.with_name("python.exe")
    return [str(py), str(HERE / "narrate.py")]


def icon_path():
    for p in (Path(getattr(sys, "_MEIPASS", HERE)) / "deck-narrator.ico", HERE / "packaging" / "deck-narrator.ico"):
        if p.exists():
            return p
    return None


def config_path():
    base = os.environ.get("APPDATA") if IS_WINDOWS else os.environ.get("XDG_CONFIG_HOME")
    base = Path(base) if base else Path.home() / ".config"
    return base / "deck-narrator" / "gui.json"


def voice_label(v):
    gender = {"f": "female", "m": "male"}.get(v[1:2], "?")
    return f"{v}  ({narrate.LANG_NAMES.get(v[0], '?')}, {gender})"


def voice_from_label(label):
    return label.split()[0] if label.strip() else narrate.DEFAULT_VOICE


def build_args(f, mode):
    """Form values (a dict) -> CLI arguments for one action. Pure, so it's testable.

    mode: "video", "builds", "phonemes" (whole deck), "phonemes_text", "sample".
    Raises ValueError with a user-facing message when something required is missing.
    """
    args = ["--voice", f["voice"], "--device", f["device"]]
    if f.get("pronunciations"):
        args += ["--pronunciations", f["pronunciations"]]

    if mode == "phonemes_text":
        if not f.get("phonemes_text", "").strip():
            raise ValueError("Type a word or phrase to see its phonemes.")
        return args + ["--phonemes", f["phonemes_text"]]
    if mode == "sample":
        if not f.get("sample_text", "").strip():
            raise ValueError("Type something for the voice to say.")
        return args + ["--speed", f["speed"], "--sample", f["sample_text"], "-o", f["sample_out"]]

    if not f.get("deck"):
        raise ValueError("Choose a PowerPoint deck (.pptx) first.")
    args = [f["deck"]] + args
    if f.get("slides", "").strip():
        args += ["--slides", f["slides"].replace(" ", "")]
    if f.get("no_builds"):
        args.append("--no-builds")
    if mode == "builds":
        return args + ["--show-builds"]
    if mode == "phonemes":
        return args + ["--show-phonemes"]

    if f.get("output"):
        args += ["-o", f["output"]]
    args += ["--speed", f["speed"], "--pad", f["pad"], "--empty-duration", f["empty_duration"],
             "--build-hold", f["build_hold"]]
    if f.get("skip_empty"):
        args.append("--skip-empty")
    if f.get("keep_temp"):
        args.append("--keep-temp")
    return args


def refresh_path():
    """Windows: reload PATH from the registry, as a new terminal would see it."""
    import winreg
    parts = []
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, key) as k:
                parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
        except OSError:
            pass
    if parts:
        os.environ["PATH"] = ";".join(parts)


def open_path(path):
    """Open a file or folder with the system's default app."""
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 (a path the user chose or the tool wrote)
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def play_wav(path):
    if IS_WINDOWS:
        import winsound
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
        return
    for player in (["aplay", "-q"], ["paplay"], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]):
        try:
            subprocess.Popen(player + [str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
    raise OSError("no audio player found (aplay, paplay or ffplay)")


class Job:
    """One CLI run in a background process; output lines arrive on a queue."""

    def __init__(self, argv, env, on_line, on_done):
        self.lines = queue.Queue()
        self.on_line, self.on_done = on_line, on_done
        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env, creationflags=flags)
        self.cancelled = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\r\n"))
        self.proc.wait()
        self.lines.put(None)

    def pump(self):
        """Called from the Tk loop: deliver queued lines. Returns False once finished."""
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:
                    self.on_done(self.proc.returncode, self.cancelled)
                    return False
                self.on_line(line)
        except queue.Empty:
            return True

    def cancel(self):
        self.cancelled = True
        if self.proc.poll() is not None:
            return
        if IS_WINDOWS:   # take LibreOffice/ffmpeg children down with it
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            self.proc.terminate()


class App:
    def __init__(self, root, selftest=None):
        self.root = root
        self.job = None
        self.selftest = selftest
        self.last_video = None
        self.sample_wav = Path(tempfile.gettempdir()) / "deck-narrator-gui-sample.wav"
        root.title(f"{TITLE} {narrate.VERSION}")
        root.minsize(760, 640)
        if IS_WINDOWS and icon_path():
            try:
                root.iconbitmap(default=str(icon_path()))
            except tk.TclError:
                pass
        self.v = {
            "deck": tk.StringVar(), "output": tk.StringVar(),
            "voice": tk.StringVar(value=voice_label(narrate.DEFAULT_VOICE)),
            "speed": tk.StringVar(value="1.0"), "device": tk.StringVar(value="auto"),
            "pronunciations": tk.StringVar(), "slides": tk.StringVar(),
            "pad": tk.StringVar(value="0.75"), "empty_duration": tk.StringVar(value="3.0"),
            "build_hold": tk.StringVar(value=str(narrate.BUILD_HOLD)),
            "skip_empty": tk.BooleanVar(), "no_builds": tk.BooleanVar(), "keep_temp": tk.BooleanVar(),
            "allow_desktop": tk.BooleanVar(),
            "sample_text": tk.StringVar(value="Hello! This is how I sound narrating your slides."),
            "phonemes_text": tk.StringVar(),
        }
        self.load_settings()
        self.build()
        self.check_dependencies()
        root.protocol("WM_DELETE_WINDOW", self.quit)

    # ------------------------------------------------------------ layout

    def build(self):
        pad = {"padx": 6, "pady": 3}
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        self.banner = ttk.Frame(outer)
        self.banner.grid(row=0, column=0, sticky="ew")
        self.banner.columnconfigure(0, weight=1)
        self.banner_text = ttk.Label(self.banner, foreground="#a00000", wraplength=560, justify="left")
        self.banner_text.grid(row=0, column=0, rowspan=2, sticky="w")
        if IS_WINDOWS:
            ttk.Button(self.banner, text="Install them", command=self.install_deps).grid(row=0, column=1, padx=3)
        ttk.Button(self.banner, text="Check again", command=self.check_dependencies).grid(row=1, column=1, padx=3, pady=2)

        files = ttk.LabelFrame(outer, text="Files", padding=6)
        files.grid(row=1, column=0, sticky="ew", pady=4)
        files.columnconfigure(1, weight=1)
        ttk.Label(files, text="Deck (.pptx)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.v["deck"]).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Browse...", command=self.pick_deck).grid(row=0, column=2, **pad)
        ttk.Label(files, text="Save video as").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.v["output"]).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Browse...", command=self.pick_output).grid(row=1, column=2, **pad)
        ttk.Label(files, text="Leave blank to save next to the deck, with the same name.",
                  foreground="#555").grid(row=2, column=1, sticky="w", padx=6)

        voice = ttk.LabelFrame(outer, text="Voice", padding=6)
        voice.grid(row=2, column=0, sticky="ew", pady=4)
        voice.columnconfigure(1, weight=1)
        ttk.Label(voice, text="Voice").grid(row=0, column=0, sticky="w", **pad)
        ttk.Combobox(voice, textvariable=self.v["voice"], state="readonly", width=40,
                     values=[voice_label(x) for x in narrate.KNOWN_VOICES]).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(voice, text="Speed").grid(row=0, column=2, sticky="e", **pad)
        ttk.Spinbox(voice, textvariable=self.v["speed"], from_=0.5, to=2.0, increment=0.05,
                    width=6).grid(row=0, column=3, sticky="w", **pad)
        ttk.Label(voice, text="Try it").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(voice, textvariable=self.v["sample_text"]).grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        self.sample_btn = ttk.Button(voice, text="Play sample", command=lambda: self.run("sample"))
        self.sample_btn.grid(row=1, column=3, **pad)
        ttk.Label(voice, text="[voice: am_michael] in the notes switches narrator mid-deck.",
                  foreground="#555").grid(row=2, column=1, columnspan=3, sticky="w", padx=6)

        pron = ttk.LabelFrame(outer, text="Pronunciation", padding=6)
        pron.grid(row=3, column=0, sticky="ew", pady=4)
        pron.columnconfigure(1, weight=1)
        ttk.Label(pron, text="Dictionary").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(pron, textvariable=self.v["pronunciations"]).grid(row=0, column=1, sticky="ew", **pad)
        btns = ttk.Frame(pron)
        btns.grid(row=0, column=2, sticky="e")
        ttk.Button(btns, text="Import...", command=self.pick_dict).pack(side="left", padx=2)
        ttk.Button(btns, text="New...", command=self.new_dict).pack(side="left", padx=2)
        ttk.Button(btns, text="Edit", command=self.edit_dict).pack(side="left", padx=2)
        ttk.Button(btns, text="Clear", command=lambda: self.v["pronunciations"].set("")).pack(side="left", padx=2)
        ttk.Label(pron, text="Phonemes for").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(pron, textvariable=self.v["phonemes_text"]).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(pron, text="Show", command=lambda: self.run("phonemes_text")).grid(row=1, column=2, sticky="w", **pad)

        opts = ttk.LabelFrame(outer, text="Slides and timing", padding=6)
        opts.grid(row=4, column=0, sticky="ew", pady=4)
        ttk.Label(opts, text="Only slides").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(opts, textvariable=self.v["slides"], width=14).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(opts, text="e.g. 3-5 or 1,4,6-8; blank = all", foreground="#555").grid(
            row=0, column=2, columnspan=4, sticky="w", **pad)
        for col, (key, label, hi) in enumerate([("pad", "Pause around narration (s)", 5),
                                                ("empty_duration", "Slide with no notes (s)", 30),
                                                ("build_hold", "Silent build step (s)", 10)]):
            ttk.Label(opts, text=label).grid(row=1, column=col * 2, sticky="w", **pad)
            ttk.Spinbox(opts, textvariable=self.v[key], from_=0, to=hi, increment=0.25, width=6).grid(
                row=1, column=col * 2 + 1, sticky="w", **pad)
        checks = ttk.Frame(opts)
        checks.grid(row=2, column=0, columnspan=6, sticky="w")
        for key, label in [("skip_empty", "Skip slides with no notes"),
                           ("no_builds", "Ignore animations"),
                           ("keep_temp", "Keep temp files"),
                           ("allow_desktop", "Allow saving to a Desktop folder")]:
            ttk.Checkbutton(checks, text=label, variable=self.v[key]).pack(side="left", padx=6, pady=3)
        ttk.Label(opts, text="Run voice on").grid(row=3, column=0, sticky="w", **pad)
        ttk.Combobox(opts, textvariable=self.v["device"], state="readonly", width=8,
                     values=["auto", "cuda", "cpu"]).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(opts, text="auto = NVIDIA GPU if there is one", foreground="#555").grid(
            row=3, column=2, columnspan=4, sticky="w", **pad)

        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, sticky="ew", pady=6)
        self.make_btn = ttk.Button(actions, text="Make video", command=lambda: self.run("video"))
        self.make_btn.pack(side="left", padx=3)
        ttk.Button(actions, text="Check builds", command=lambda: self.run("builds")).pack(side="left", padx=3)
        ttk.Button(actions, text="Show phonemes", command=lambda: self.run("phonemes")).pack(side="left", padx=3)
        self.cancel_btn = ttk.Button(actions, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=3)
        self.folder_btn = ttk.Button(actions, text="Open folder", command=self.open_folder, state="disabled")
        self.folder_btn.pack(side="right", padx=3)
        self.open_btn = ttk.Button(actions, text="Play video", command=self.open_video, state="disabled")
        self.open_btn.pack(side="right", padx=3)

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.grid(row=6, column=0, sticky="ew")
        self.status = ttk.Label(outer, text="Ready.")
        self.status.grid(row=7, column=0, sticky="w", pady=2)

        self.log = ScrolledText(outer, height=12, wrap="word", font=("Consolas" if IS_WINDOWS else "monospace", 9))
        self.log.grid(row=8, column=0, sticky="nsew")
        self.log.configure(state="disabled")
        outer.rowconfigure(8, weight=1)

    # ------------------------------------------------------------ settings

    SAVED = ("voice", "speed", "device", "pronunciations", "pad", "empty_duration", "build_hold",
             "skip_empty", "no_builds", "keep_temp", "allow_desktop", "sample_text")

    def load_settings(self):
        self.last_dir = str(Path.home())
        try:
            data = json.loads(config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for k in self.SAVED:
            if k in data:
                try:
                    self.v[k].set(data[k])
                except tk.TclError:
                    pass
        self.last_dir = data.get("last_dir", self.last_dir)

    def save_settings(self):
        data = {k: self.v[k].get() for k in self.SAVED}
        data["last_dir"] = self.last_dir
        try:
            config_path().parent.mkdir(parents=True, exist_ok=True)
            config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ pickers

    def pick_deck(self):
        p = filedialog.askopenfilename(title="Choose a PowerPoint deck", initialdir=self.last_dir,
                                       filetypes=[("PowerPoint", "*.pptx"), ("All files", "*.*")])
        if p:
            self.v["deck"].set(p)
            self.last_dir = str(Path(p).parent)

    def pick_output(self):
        deck = self.v["deck"].get()
        p = filedialog.asksaveasfilename(
            title="Save video as", defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4")],
            initialdir=str(Path(deck).parent) if deck else self.last_dir,
            initialfile=(Path(deck).stem + ".mp4") if deck else "narrated.mp4")
        if p:
            self.v["output"].set(p)

    def pick_dict(self):
        p = filedialog.askopenfilename(title="Import a pronunciation dictionary", initialdir=self.last_dir,
                                       filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if p:
            try:
                narrate.load_pronunciations(p)
            except narrate.Fail as e:
                messagebox.showerror(TITLE, f"That file isn't a valid dictionary:\n\n{e}")
                return
            except (OSError, UnicodeDecodeError) as e:
                messagebox.showerror(TITLE, f"Couldn't read that file:\n\n{e}")
                return
            self.v["pronunciations"].set(p)

    def new_dict(self):
        p = filedialog.asksaveasfilename(title="New pronunciation dictionary", defaultextension=".txt",
                                         initialdir=self.last_dir, initialfile="pronunciations.txt",
                                         filetypes=[("Text", "*.txt")])
        if not p:
            return
        if not Path(p).exists():
            Path(p).write_text(DICT_TEMPLATE, encoding="utf-8")
        self.v["pronunciations"].set(p)
        self.edit_dict()

    def edit_dict(self):
        p = self.v["pronunciations"].get()
        if not p or not Path(p).is_file():
            messagebox.showinfo(TITLE, "Import or create a dictionary first.")
            return
        if IS_WINDOWS:
            subprocess.Popen(["notepad.exe", p])
        else:
            open_path(p)

    # ------------------------------------------------------------ running

    WINGET = ("winget install -e --id TheDocumentFoundation.LibreOffice --accept-source-agreements "
              "--accept-package-agreements & winget install -e --id Gyan.FFmpeg --accept-source-agreements "
              "--accept-package-agreements")

    def install_deps(self):
        """Run winget in a visible console, so its progress and any prompts can be seen."""
        subprocess.Popen(["cmd", "/c", "start", "Installing LibreOffice and ffmpeg", "cmd", "/k",
                          self.WINGET + " & echo. & echo Done. Close this window, then press Check again."])

    def check_dependencies(self):
        if IS_WINDOWS:
            refresh_path()      # pick up what winget just installed, without a restart
        missing = []
        for name, finder in (("LibreOffice", narrate.find_soffice), ("ffmpeg", narrate.find_ffmpeg)):
            try:
                finder()
            except narrate.Fail:
                missing.append(name)
        if not missing:
            self.banner.grid_remove()
            return
        how = ("Press Install them (uses winget), then Check again." if IS_WINDOWS
               else "Install them:  sudo apt install libreoffice-impress ffmpeg")
        self.banner_text.configure(text=f"Missing: {' and '.join(missing)}. Making a video needs both "
                                        f"(LibreOffice draws the slides, ffmpeg makes the MP4). {how}")
        self.banner.grid()

    def form(self):
        f = {k: (v.get() if not isinstance(v, tk.BooleanVar) else bool(v.get())) for k, v in self.v.items()}
        f["voice"] = voice_from_label(f["voice"])
        f["sample_out"] = str(self.sample_wav)
        for k in ("deck", "output", "pronunciations"):
            f[k] = f[k].strip()
        return f

    def run(self, mode):
        if self.job:
            return
        try:
            args = build_args(self.form(), mode)
        except ValueError as e:
            messagebox.showwarning(TITLE, str(e))
            return
        self.save_settings()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        if self.v["allow_desktop"].get():
            env["DECK_NARRATOR_ALLOW_DESKTOP"] = "1"
        argv = cli_command() + args
        self.mode = mode
        self.out_lines = []
        self.clear_log()
        self.append("> deck-narrator " + " ".join(shlex.quote(a) for a in args))
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status.configure(text={"video": "Making the video...", "sample": "Synthesizing the sample...",
                                    "builds": "Reading the deck's animations..."}.get(mode, "Working..."))
        self.cancel_btn.configure(state="normal")
        self.make_btn.configure(state="disabled")
        self.sample_btn.configure(state="disabled")
        try:
            self.job = Job(argv, env, self.on_line, self.on_done)
        except OSError as e:
            self.on_done(-1, False)
            self.append(f"Couldn't start {argv[0]}: {e}")
            return
        self.poll()

    def poll(self):
        if self.job and self.job.pump():
            self.root.after(100, self.poll)

    def on_line(self, line):
        self.out_lines.append(line)
        self.append(line)
        m = re.match(r"\[(\d+)/(\d+)\] slide", line) or re.match(r"Rendering build pass (\d+)/(\d+)", line)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            phase = 0 if line.startswith("Rendering") else 1     # slides render first, then the voice
            self.progress.stop()
            self.progress.configure(mode="determinate", value=(phase * 50) + 50 * done / total)
            self.status.configure(text=line)
        elif line.startswith(("Loading Kokoro", "Measuring loudness", "Encoding")):
            self.status.configure(text=line)

    def on_done(self, code, cancelled):
        self.job = None
        self.progress.stop()
        self.progress.configure(mode="determinate", value=100 if code == 0 else 0)
        self.cancel_btn.configure(state="disabled")
        self.make_btn.configure(state="normal")
        self.sample_btn.configure(state="normal")
        if cancelled:
            self.status.configure(text="Cancelled.")
        elif code != 0:
            err = next((l for l in reversed(self.out_lines) if "error:" in l), "it failed; see the log")
            self.status.configure(text=err.split("error:", 1)[-1].strip()[:200])
        elif self.mode == "video":
            vids = [l for l in self.out_lines if l.lower().endswith(".mp4") and Path(l).is_file()]
            self.last_video = Path(vids[-1]) if vids else None
            self.status.configure(text=f"Done: {self.last_video}" if self.last_video else "Done.")
            state = "normal" if self.last_video else "disabled"
            self.open_btn.configure(state=state)
            self.folder_btn.configure(state=state)
        elif self.mode == "sample":
            self.status.configure(text="Playing the sample.")
            try:
                play_wav(self.sample_wav)
            except Exception as e:
                self.status.configure(text=f"Sample made but couldn't play it: {e}")
        else:
            self.status.configure(text="Done.")
        if self.selftest:
            self.selftest(code)

    def cancel(self):
        if self.job:
            self.job.cancel()

    def open_video(self):
        if self.last_video and self.last_video.exists():
            open_path(self.last_video)

    def open_folder(self):
        if self.last_video:
            if IS_WINDOWS:
                subprocess.Popen(["explorer", "/select,", str(self.last_video)])
            else:
                open_path(self.last_video.parent)

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def append(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def quit(self):
        if self.job:
            if not messagebox.askyesno(TITLE, "A job is still running. Stop it and quit?"):
                return
            self.job.cancel()
        self.save_settings()
        self.root.destroy()


def main(argv=None):
    """GUI entry point. Test-only: --selftest MODE DECK RESULT_FILE [LINGER_SECONDS]
    opens the window, presses the button for MODE (video, builds, phonemes, sample)
    on DECK, writes the exit code and log to RESULT_FILE, keeps the window up for
    LINGER_SECONDS (for a screenshot) and exits with 0 on success."""
    argv = sys.argv[1:] if argv is None else argv
    root = tk.Tk()
    exit_code = [0]
    if argv[:1] == ["--selftest"]:
        mode, deck, result = argv[1], argv[2], Path(argv[3])
        linger = float(argv[4]) if len(argv) > 4 else 0

        def finished(code):
            video = f"video {app.last_video}\n" if app.last_video else ""
            result.write_text(f"exit {code}\n{video}" + "\n".join(app.out_lines) + "\n", encoding="utf-8")
            exit_code[0] = 0 if code == 0 else 1
            root.after(int(linger * 1000), root.destroy)

        app = App(root, selftest=finished)
        app.v["deck"].set(deck)
        root.after(500, lambda: app.run(mode))
    else:
        app = App(root)
        if argv:
            app.v["deck"].set(argv[0])     # "Open with" / drag onto the exe
    root.mainloop()
    return exit_code[0]


if __name__ == "__main__":
    sys.exit(main())
