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
    "update_voices",   # the "Check for new voices" option and button
    "check_pronunciation", "json", "fix_word",   # Check pronunciation and its window
    "renderer",        # Options tab: "Draw slides with"
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


# Brand palette, from the ChatShot app: pastel purple and pink on dark amethyst.
PALETTES = {
    "dark": {"bg": "#1C1526", "panel": "#241B30", "field": "#160F1E", "ink": "#F1E9FA", "muted": "#A996B8",
             "accent": "#C2A0E2", "accent_dim": "#A784C6", "pink": "#FF8FD0", "danger": "#E08BB0",
             "border": "#3A2D4A", "on_accent": "#1C1526"},
    "light": {"bg": "#F6F1FB", "panel": "#FFFCFF", "field": "#FFFFFF", "ink": "#2E1A3D", "muted": "#6E5A80",
              "accent": "#A784C6", "accent_dim": "#8F6DB0", "pink": "#E0559E", "danger": "#C1567F",
              "border": "#D9CCE6", "on_accent": "#FFFBFF"},
}


def system_prefers_dark():
    """Windows: the "app mode" in Settings > Personalization > Colors. Elsewhere: dark,
    the brand's default. DECK_NARRATOR_THEME=light or dark overrides both."""
    forced = os.environ.get("DECK_NARRATOR_THEME", "").lower()
    if forced in ("light", "dark"):
        return forced == "dark"
    if not IS_WINDOWS:
        return True
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return True


def apply_theme(root, dark):
    """Style every ttk widget with the brand palette. Returns the palette."""
    c = PALETTES["dark" if dark else "light"]
    st = ttk.Style(root)
    st.theme_use("clam")              # the one built-in theme whose colors can all be set
    from tkinter import font as tkfont
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        f = tkfont.nametofont(name)
        if IS_WINDOWS:
            f.configure(family="Segoe UI")
        f.configure(size=10)
    base = tkfont.nametofont("TkDefaultFont")
    bold = base.copy()
    bold.configure(weight="bold")
    title = base.copy()
    title.configure(size=16, weight="bold")
    root._fonts = (bold, title)       # named fonts vanish when nothing holds them
    root.configure(bg=c["bg"])
    st.configure(".", background=c["bg"], foreground=c["ink"], fieldbackground=c["field"], font=base,
                 bordercolor=c["border"], lightcolor=c["panel"], darkcolor=c["panel"], troughcolor=c["field"],
                 focuscolor=c["accent"], selectbackground=c["accent_dim"], selectforeground=c["on_accent"],
                 insertcolor=c["ink"], arrowcolor=c["accent"])
    st.map(".", foreground=[("disabled", c["muted"])])
    st.configure("TLabelframe", background=c["bg"], bordercolor=c["border"], relief="solid")
    st.configure("TLabelframe.Label", background=c["bg"], foreground=c["accent"], font=bold)
    st.configure("Title.TLabel", foreground=c["accent"], font=title)
    st.configure("Hint.TLabel", foreground=c["muted"])
    st.configure("Link.TButton", background=c["bg"], foreground=c["accent"], bordercolor=c["bg"],
                 lightcolor=c["bg"], darkcolor=c["bg"], padding=(0, 2), font=bold)
    st.map("Link.TButton", background=[("active", c["bg"]), ("pressed", c["bg"])],
           foreground=[("active", c["pink"])])
    st.configure("Warn.TLabel", foreground=c["danger"])
    st.configure("TButton", background=c["panel"], foreground=c["ink"], bordercolor=c["border"], padding=(10, 4))
    st.map("TButton", background=[("disabled", c["bg"]), ("pressed", c["field"]), ("active", c["border"])],
           foreground=[("disabled", c["muted"])])
    st.configure("Accent.TButton", background=c["accent"], foreground=c["on_accent"], bordercolor=c["accent"],
                 font=bold)
    st.map("Accent.TButton", background=[("disabled", c["border"]), ("pressed", c["accent_dim"]), ("active", c["pink"])],
           foreground=[("disabled", c["muted"])])
    for w in ("TEntry", "TSpinbox", "TCombobox"):
        st.configure(w, fieldbackground=c["field"], foreground=c["ink"], insertcolor=c["ink"],
                     bordercolor=c["border"], lightcolor=c["field"], darkcolor=c["field"], padding=3)
        st.map(w, fieldbackground=[("readonly", c["field"]), ("disabled", c["bg"])],
               bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])])
    st.map("TCombobox", selectbackground=[("readonly", c["field"])], selectforeground=[("readonly", c["ink"])])
    st.configure("TCheckbutton", background=c["bg"], indicatorbackground=c["field"], indicatormargin=4)
    st.map("TCheckbutton", background=[("active", c["bg"])],
           indicatorbackground=[("selected", c["accent"]), ("!selected", c["field"])],
           indicatorforeground=[("selected", c["on_accent"])])
    st.configure("TNotebook", background=c["bg"], bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"],
                 tabmargins=(0, 2, 0, 0))
    st.configure("TNotebook.Tab", background=c["panel"], foreground=c["muted"], bordercolor=c["border"],
                 lightcolor=c["panel"], darkcolor=c["panel"], padding=(12, 5), font=bold)
    st.map("TNotebook.Tab", background=[("selected", c["bg"]), ("active", c["bg"])],
           foreground=[("selected", c["accent"]), ("active", c["pink"])],
           lightcolor=[("selected", c["accent"])], darkcolor=[("selected", c["bg"])], expand=[("selected", (0, 2, 0, 0))])
    st.configure("Horizontal.TProgressbar", background=c["pink"], troughcolor=c["field"], bordercolor=c["border"],
                 lightcolor=c["pink"], darkcolor=c["pink"])
    st.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["ink"],
                 bordercolor=c["border"], rowheight=24)
    st.map("Treeview", background=[("selected", c["accent_dim"])], foreground=[("selected", c["on_accent"])])
    st.configure("Treeview.Heading", background=c["panel"], foreground=c["accent"], font=bold, relief="flat")
    st.map("Treeview.Heading", background=[("active", c["panel"])])
    st.configure("Vertical.TScrollbar", background=c["panel"], troughcolor=c["field"], bordercolor=c["border"])
    for opt, val in (("background", c["field"]), ("foreground", c["ink"]),
                     ("selectBackground", c["accent_dim"]), ("selectForeground", c["on_accent"])):
        root.option_add(f"*TCombobox*Listbox.{opt}", val)
    return c


def asset_path(name):
    """A file shipped next to the program (frozen) or in packaging/ (source)."""
    for p in (Path(getattr(sys, "_MEIPASS", HERE)) / name, Path(sys.executable).parent / name, HERE / "packaging" / name):
        if p.exists():
            return p
    return None


def icon_path():
    return asset_path("deck-narrator.ico")


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

    mode: "video", "builds", "check" (pronunciation), "phonemes" (whole deck), "phonemes_text", "sample".
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
    if mode == "check":
        return args + ["--check-pronunciation", "--json"]

    if f.get("output"):
        args += ["-o", f["output"]]
    args += ["--speed", f["speed"], "--pad", f["pad"], "--empty-duration", f["empty_duration"],
             "--build-hold", f["build_hold"], "--renderer", f.get("renderer") or "auto"]
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


class PronunciationReview:
    """The Check pronunciation window: the words that may be said wrong, each way of saying
    one with a Play button, and Use this, which writes the choice into the deck's notes."""

    KINDS = {"heteronym": "more than one way to say it", "unknown": "not in the dictionary",
             "spelled": "all capitals: spelled out"}

    def __init__(self, app, issues, deck):
        self.app, self.issues, self.deck = app, issues, deck
        self.job = None
        self.wav = Path(tempfile.gettempdir()) / "deck-narrator-review.wav"
        c = app.colors
        w = self.win = tk.Toplevel(app.root)
        w.title(f"{TITLE}: check pronunciation")
        w.configure(bg=c["bg"])
        w.transient(app.root)
        outer = ttk.Frame(w, padding=(12, 10))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)
        ttk.Label(outer, text=f"{len(issues)} word(s) that may be said wrong in {Path(deck).name}. Pick one, "
                              "press Play to hear each way, then Use this to fix it in the deck's notes.",
                  wraplength=640, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 6))
        frame = ttk.Frame(outer)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=("slide", "word", "why", "status"), show="headings", height=8,
                                 selectmode="browse")
        for col, text, width in (("slide", "Slide", 50), ("word", "Word", 120), ("why", "Why", 230),
                                 ("status", "Status", 200)):
            self.tree.heading(col, text=text, anchor="w")
            self.tree.column(col, width=width, anchor="w", stretch=col == "status")
        for i, issue in enumerate(issues):
            self.tree.insert("", "end", iid=str(i), values=(issue["slide"], issue["word"],
                                                            self.KINDS.get(issue["kind"], issue["kind"]),
                                                            f"now /{issue['current']}/"))
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show())

        self.detail = ttk.LabelFrame(outer, text="Choose how it's said", padding=(8, 4, 8, 6))
        self.detail.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.detail.columnconfigure(1, weight=1)
        self.status = ttk.Label(outer, text="", style="Hint.TLabel")
        self.status.grid(row=3, column=0, sticky="w", pady=(6, 0))
        btns = ttk.Frame(outer)
        btns.grid(row=4, column=0, sticky="e", pady=(6, 0))
        ttk.Button(btns, text="Close", command=self.close).pack(side="right")
        w.protocol("WM_DELETE_WINDOW", self.close)
        app.root.update_idletasks()
        w.geometry(f"720x520+{app.root.winfo_rootx() + 30}+{max(0, app.root.winfo_rooty() - 20)}")
        if issues:
            self.tree.selection_set("0")
        else:
            ttk.Label(self.detail, text="Nothing to check: every word has one clear pronunciation.").grid(
                row=0, column=0, sticky="w")

    def show(self):
        for child in self.detail.winfo_children():
            child.destroy()
        sel = self.tree.selection()
        if not sel:
            return
        issue = self.issues[int(sel[0])]
        ttk.Label(self.detail, text=f"Slide {issue['slide']} ({issue['voice']}):  {issue['sentence']}",
                  wraplength=660, justify="left").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))
        row = 1
        for o in issue["options"]:
            ttk.Label(self.detail, text=f"/{o['phonemes']}/").grid(row=row, column=0, sticky="w", padx=(0, 8))
            ttk.Label(self.detail, text=o["label"], style="Hint.TLabel").grid(row=row, column=1, sticky="w")
            ttk.Button(self.detail, text="Play", command=lambda o=o: self.play(issue, o["say"])).grid(
                row=row, column=2, padx=3, pady=1)
            ttk.Button(self.detail, text="Use this", command=lambda o=o: self.use(sel[0], issue, o["phonemes"])).grid(
                row=row, column=3, padx=3, pady=1)
            row += 1
        ttk.Label(self.detail, text="Sounds like").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(4, 0))
        spell = tk.StringVar()
        ttk.Entry(self.detail, textvariable=spell).grid(row=row, column=1, sticky="ew", pady=(4, 0))
        ttk.Button(self.detail, text="Play", command=lambda: self.custom(sel[0], issue, spell.get(), False)).grid(
            row=row, column=2, padx=3, pady=(4, 0))
        ttk.Button(self.detail, text="Use this", command=lambda: self.custom(sel[0], issue, spell.get(), True)).grid(
            row=row, column=3, padx=3, pady=(4, 0))
        ttk.Label(self.detail, text="Or type a spelling that sounds right, e.g. \"op swat\" or \"zee scaler\".",
                  style="Hint.TLabel").grid(row=row + 1, column=1, columnspan=3, sticky="w")

    def run(self, args, done, what):
        if self.job:
            self.status.configure(text="Still busy with the last one...")
            return
        out = []
        self.status.configure(text=what)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")

        def finished(code, cancelled):
            self.job = None
            if code == 0:
                done(out)
            else:
                err = next((l for l in reversed(out) if "error:" in l), "it failed")
                self.status.configure(text=err.split("error:", 1)[-1].strip()[:200])
        try:
            self.job = Job(cli_command() + args, env, out.append, finished)
        except OSError as e:
            self.status.configure(text=f"Couldn't start the command line program: {e}")
            return
        self.poll()

    def poll(self):
        if self.job and self.job.pump():
            self.win.after(100, self.poll)

    def play(self, issue, text):
        def done(out):
            try:
                play_wav(self.wav)
                self.status.configure(text="Playing.")
            except Exception as e:
                self.status.configure(text=f"Couldn't play it: {e}")
        self.run(["--voice", issue["voice"], "--speed", self.app.v["speed"].get(), "--sample", text,
                  "-o", str(self.wav)], done, "Making the sample...")

    def use(self, iid, issue, phonemes):
        def done(out):
            self.tree.set(iid, "status", f"fixed: /{phonemes}/")
            self.status.configure(text=f"Saved in slide {issue['slide']}'s notes. The original deck is kept as "
                                       f"\"{Path(self.deck).stem} (before deck-narrator).pptx\".")
            nxt = self.tree.next(iid)
            if nxt:
                self.tree.selection_set(nxt)
                self.tree.see(nxt)
        self.run([self.deck, "--fix-word", str(issue["slide"]), issue["word"], str(issue["n"]), phonemes],
                 done, "Saving the deck...")

    def custom(self, iid, issue, spelling, use):
        spelling = spelling.strip()
        if not spelling:
            self.status.configure(text="Type how the word should sound first.")
            return

        def done(out):
            ps = next((l for l in reversed(out) if l.strip() and not l.startswith(("Loading", "deck-narrator"))), "")
            ps = ps.strip()
            if not ps:
                self.status.configure(text="Couldn't work out phonemes for that spelling.")
                return
            if use:
                self.use(iid, issue, ps)
            else:
                say = narrate.with_override(issue["sentence"], issue["word"], issue["n_in_sentence"], ps)
                self.play(issue, say or spelling)
        self.run(["--voice", issue["voice"], "--phonemes", spelling], done, "Working out the phonemes...")

    def close(self):
        if self.job:
            self.job.cancel()
        self.win.destroy()
        self.app.review = None


class App:
    def __init__(self, root, selftest=None):
        self.root = root
        self.job = None
        self.selftest = selftest
        self.last_video = None
        self.sample_wav = Path(tempfile.gettempdir()) / "deck-narrator-gui-sample.wav"
        root.title(f"{TITLE} {narrate.VERSION}")
        self.colors = apply_theme(root, system_prefers_dark())
        try:
            if IS_WINDOWS and icon_path():
                root.iconbitmap(default=str(icon_path()))
            elif asset_path("deck-narrator.png"):
                self.icon_img = tk.PhotoImage(file=str(asset_path("deck-narrator.png")))
                root.iconphoto(True, self.icon_img)
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
            "sample_text": tk.StringVar(value=narrate.DEFAULT_SAMPLE_TEXT),
            "phonemes_text": tk.StringVar(),
            "check_voices": tk.BooleanVar(value=True),
            "renderer": tk.StringVar(value="auto"),
            "tab": tk.StringVar(value="0"),
        }
        self.last_voice_check = 0.0
        self.load_settings()
        self.build()
        self.fit_to_screen()
        self.check_dependencies()
        root.protocol("WM_DELETE_WINDOW", self.quit)
        if self.v["check_voices"].get() and not selftest:
            root.after(1500, self.check_voices)

    def fit_to_screen(self):
        """Open at the layout's natural size, but never taller or wider than the screen's
        work area (a 1024x768 screen minus the taskbar): the log pane shrinks instead."""
        self.root.geometry("")            # let the layout ask for its natural size again
        self.root.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = min(self.root.winfo_reqwidth(), sw - 40)
        h = min(self.root.winfo_reqheight(), sh - 90)
        self.root.minsize(min(700, w), min(560, h))
        self.root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h - 60) // 2)}")

    # ------------------------------------------------------------ layout

    def build(self):
        pad = {"padx": 5, "pady": 3}
        outer = ttk.Frame(self.root, padding=(12, 8, 12, 10))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        head = ttk.Frame(outer)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        if asset_path("deck-narrator.png"):
            try:
                self.logo = tk.PhotoImage(file=str(asset_path("deck-narrator.png"))).subsample(8)
                ttk.Label(head, image=self.logo).pack(side="left", padx=(0, 8))
            except tk.TclError:
                pass
        ttk.Label(head, text=TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=f"  {narrate.VERSION}  ·  speaker notes to narrated video", style="Hint.TLabel").pack(
            side="left", pady=(6, 0))

        self.banner = ttk.Frame(outer)
        self.banner.grid(row=1, column=0, sticky="ew")
        self.banner.columnconfigure(0, weight=1)
        self.banner_text = ttk.Label(self.banner, style="Warn.TLabel", wraplength=520, justify="left")
        self.banner_text.grid(row=0, column=0, rowspan=2, sticky="w")
        if IS_WINDOWS:
            ttk.Button(self.banner, text="Install LibreOffice", command=self.install_deps).grid(row=0, column=1, padx=3)
        ttk.Button(self.banner, text="Check again", command=self.check_dependencies).grid(row=1, column=1, padx=3, pady=2)

        # One tab per part of the job; the log is a tab too, shown when something runs.
        self.tabs = ttk.Notebook(outer)
        self.tabs.grid(row=2, column=0, sticky="nsew", pady=(4, 0))
        outer.rowconfigure(2, weight=1)

        def tab(text):
            f = ttk.Frame(self.tabs, padding=(10, 8))
            f.columnconfigure(1, weight=1)
            self.tabs.add(f, text=f"  {text}  ")
            return f

        files = tab("Deck")
        ttk.Label(files, text="Deck (.pptx)").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.v["deck"]).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Browse...", command=self.pick_deck).grid(row=0, column=2, **pad)
        ttk.Label(files, text="Save video as").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.v["output"]).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(files, text="Browse...", command=self.pick_output).grid(row=1, column=2, **pad)
        ttk.Label(files, text="Leave blank to save next to the deck, with the same name.",
                  style="Hint.TLabel").grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(files, text="Only slides").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(files, textvariable=self.v["slides"], width=14).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(files, text="e.g. 3-5 or 1,4,6-8; blank = all", style="Hint.TLabel").grid(
            row=4, column=1, sticky="w", padx=6)

        voice = tab("Voice")
        ttk.Label(voice, text="Voice").grid(row=0, column=0, sticky="w", **pad)
        self.voice_box = ttk.Combobox(voice, textvariable=self.v["voice"], state="readonly", width=40,
                                      values=[voice_label(x) for x in narrate.available_voices()])
        self.voice_box.grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(voice, text="Speed").grid(row=0, column=2, sticky="e", **pad)
        ttk.Spinbox(voice, textvariable=self.v["speed"], from_=0.5, to=2.0, increment=0.05,
                    width=6).grid(row=0, column=3, sticky="w", **pad)
        ttk.Label(voice, text="[voice: am_michael] in the notes switches narrator mid-deck.",
                  style="Hint.TLabel").grid(row=1, column=1, columnspan=3, sticky="w", padx=6)
        ttk.Label(voice, text="Try it").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(voice, textvariable=self.v["sample_text"]).grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        self.sample_btn = ttk.Button(voice, text="Play sample", command=lambda: self.run("sample"))
        self.sample_btn.grid(row=2, column=3, **pad)
        voice_check = ttk.Frame(voice)
        voice_check.grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Checkbutton(voice_check, text="Check for new voices at startup",
                        variable=self.v["check_voices"]).pack(side="left", padx=4)
        ttk.Button(voice_check, text="Check now", command=lambda: self.check_voices(force=True)).pack(side="left", padx=4)

        pron = tab("Pronunciation")
        ttk.Label(pron, text="Dictionary").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(pron, textvariable=self.v["pronunciations"]).grid(row=0, column=1, sticky="ew", **pad)
        btns = ttk.Frame(pron)
        btns.grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Button(btns, text="Import...", command=self.pick_dict).pack(side="left", padx=3)
        ttk.Button(btns, text="New...", command=self.new_dict).pack(side="left", padx=3)
        ttk.Button(btns, text="Edit", command=self.edit_dict).pack(side="left", padx=3)
        ttk.Button(btns, text="Clear", command=lambda: self.v["pronunciations"].set("")).pack(side="left", padx=3)
        ttk.Label(pron, text="One word=sounds-like per line, applied to the notes before speaking.",
                  style="Hint.TLabel").grid(row=2, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Label(pron, text="Phonemes for").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(pron, textvariable=self.v["phonemes_text"]).grid(row=3, column=1, sticky="ew", **pad)
        ttk.Button(pron, text="Show", command=lambda: self.run("phonemes_text")).grid(row=3, column=2, sticky="w", **pad)
        ttk.Label(pron, text="Whole deck").grid(row=4, column=0, sticky="w", **pad)
        ttk.Button(pron, text="Show every slide's phonemes", command=lambda: self.run("phonemes")).grid(
            row=4, column=1, sticky="w", **pad)

        opts = tab("Options")
        opts.columnconfigure(1, weight=0)
        opts.columnconfigure(2, weight=1)
        for r, (key, label, hi) in enumerate([("pad", "Pause around narration (s)", 5),
                                              ("empty_duration", "Slide with no notes (s)", 30),
                                              ("build_hold", "Silent build step (s)", 10)]):
            ttk.Label(opts, text=label).grid(row=r, column=0, sticky="w", **pad)
            ttk.Spinbox(opts, textvariable=self.v[key], from_=0, to=hi, increment=0.25, width=6).grid(
                row=r, column=1, sticky="w", **pad)
        checks = ttk.Frame(opts)
        checks.grid(row=0, column=2, rowspan=3, sticky="nw", padx=(24, 0))
        for i, (key, label) in enumerate([("skip_empty", "Skip slides with no notes"),
                                          ("no_builds", "Ignore animations"),
                                          ("keep_temp", "Keep temp files"),
                                          ("allow_desktop", "Allow saving to a Desktop folder")]):
            ttk.Checkbutton(checks, text=label, variable=self.v[key]).grid(row=i, column=0, sticky="w", pady=1)
        ttk.Label(opts, text="Draw slides with").grid(row=3, column=0, sticky="w", **pad)
        ttk.Combobox(opts, textvariable=self.v["renderer"], state="readonly", width=12,
                     values=["auto", "powerpoint", "libreoffice"]).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(opts, text="auto = PowerPoint if installed", style="Hint.TLabel").grid(
            row=3, column=2, columnspan=2, sticky="w", **pad)
        ttk.Label(opts, text="Run voice on").grid(row=4, column=0, sticky="w", **pad)
        ttk.Combobox(opts, textvariable=self.v["device"], state="readonly", width=12,
                     values=["auto", "cuda", "cpu"]).grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(opts, text="auto = NVIDIA GPU if there is one", style="Hint.TLabel").grid(
            row=4, column=2, columnspan=2, sticky="w", **pad)

        logtab = ttk.Frame(self.tabs, padding=(4, 4))
        self.tabs.add(logtab, text="  Log  ")
        self.log_tab = logtab
        logtab.columnconfigure(0, weight=1)
        logtab.rowconfigure(0, weight=1)
        c = self.colors
        self.log = ScrolledText(logtab, height=9, width=60, wrap="word",
                                font=("Consolas" if IS_WINDOWS else "monospace", 9),
                                bg=c["field"], fg=c["ink"], insertbackground=c["ink"], relief="flat",
                                selectbackground=c["accent_dim"], selectforeground=c["on_accent"],
                                highlightthickness=1, highlightbackground=c["border"], highlightcolor=c["accent"])
        try:   # the classic scrollbar: colors apply on Linux; Windows draws its own
            self.log.vbar.configure(bg=c["panel"], troughcolor=c["field"], activebackground=c["accent_dim"],
                                    highlightthickness=0, bd=0)
        except tk.TclError:
            pass
        self.log.grid(row=0, column=0, sticky="nsew")
        self.log.configure(state="disabled")
        try:
            self.tabs.select(int(self.v["tab"].get()))
        except (tk.TclError, ValueError):
            pass

        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="ew", pady=(8, 4))
        self.make_btn = ttk.Button(actions, text="Make video", style="Accent.TButton", command=lambda: self.run("video"))
        self.make_btn.pack(side="left", padx=3)
        ttk.Button(actions, text="Check builds", command=lambda: self.run("builds")).pack(side="left", padx=3)
        ttk.Button(actions, text="Check pronunciation", command=lambda: self.run("check")).pack(side="left", padx=3)
        self.cancel_btn = ttk.Button(actions, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=3)
        self.folder_btn = ttk.Button(actions, text="Open folder", command=self.open_folder, state="disabled")
        self.folder_btn.pack(side="right", padx=3)
        self.open_btn = ttk.Button(actions, text="Play video", command=self.open_video, state="disabled")
        self.open_btn.pack(side="right", padx=3)

        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=100)
        self.progress.grid(row=4, column=0, sticky="ew")
        self.status = ttk.Label(outer, text="Ready.")
        self.status.grid(row=5, column=0, sticky="w", pady=(2, 0))

    # ------------------------------------------------------------ settings

    SAVED = ("voice", "speed", "device", "pronunciations", "pad", "empty_duration", "build_hold",
             "skip_empty", "no_builds", "keep_temp", "allow_desktop", "sample_text", "check_voices", "renderer")

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
        if self.v["sample_text"].get() == "Hello! This is how I sound narrating your slides.":   # 1.1/1.2 default
            self.v["sample_text"].set(narrate.DEFAULT_SAMPLE_TEXT)
        self.v["tab"].set(str(data.get("tab", 0)))
        self.last_voice_check = float(data.get("last_voice_check", 0) or 0)

    def save_settings(self):
        data = {k: self.v[k].get() for k in self.SAVED}
        try:
            data["tab"] = min(self.tabs.index("current"), 3)   # reopen on the last form tab, not the log
        except (tk.TclError, AttributeError):
            pass
        data["last_dir"] = self.last_dir
        data["last_voice_check"] = self.last_voice_check
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

    def install_deps(self):
        """Run install-dependencies.cmd in a visible console, so its progress can be seen.
        The installer's finish page runs the same script."""
        script = asset_path("install-dependencies.cmd")
        if not script:
            messagebox.showerror(TITLE, "install-dependencies.cmd is missing from this install.")
            return
        subprocess.Popen(["cmd", "/c", "start", "Deck Narrator setup", str(script)])

    VOICE_CHECK_EVERY = 24 * 3600

    def check_voices(self, force=False):
        """Ask the CLI for new or updated voices, in the background, at most once a day
        unless forced. Offline or failing, it says so in the status line and nothing else."""
        import time
        if getattr(self, "voice_check_running", False):
            return
        if not force and time.time() - self.last_voice_check < self.VOICE_CHECK_EVERY:
            return
        self.voice_check_running = True
        self.status.configure(text="Checking for new voices...")
        flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
        result = {}

        def work():
            try:
                r = subprocess.run(cli_command() + ["--update-voices"], stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   creationflags=flags, timeout=900)
                result["line"] = next((l for l in r.stdout.splitlines() if l.startswith("voices:")), "")
                result["code"] = r.returncode
            except Exception as e:
                result["line"], result["code"] = f"voices: error {type(e).__name__}", 1

        t = threading.Thread(target=work, daemon=True)
        t.start()

        def wait():
            if t.is_alive():
                self.root.after(500, wait)
                return
            self.voice_check_running = False
            line = result.get("line", "")
            if result.get("code") == 0 and line != "voices: offline":
                self.last_voice_check = time.time()
                self.save_settings()
            self.voice_box.configure(values=[voice_label(x) for x in narrate.available_voices()])
            msg = {"voices: offline": "Couldn't check for new voices (offline). The installed voices work as usual.",
                   "voices: not bundled": "Voices download on demand in this install, so they're always current.",
                   "voices: 0 new; 0 updated": "Voices are up to date."}.get(line)
            if not msg:
                msg = (f"Voice update: {line[len('voices: '):]}" if result.get("code") == 0 and line
                       else "The voice check failed; the installed voices work as usual.")
            if not self.job:
                self.status.configure(text=msg)

        wait()

    def check_dependencies(self):
        if IS_WINDOWS:
            refresh_path()      # pick up what was just installed, without a restart
        missing = []
        try:
            narrate.find_ffmpeg()
        except narrate.Fail:
            missing.append("ffmpeg")
        if not narrate.powerpoint_installed():
            try:
                narrate.find_soffice()
            except narrate.Fail:
                missing.append("LibreOffice")
        if not missing:
            self.banner.grid_remove()
            return
        if IS_WINDOWS:
            how = ("Deck Narrator draws slides with PowerPoint or LibreOffice, and this PC has neither. "
                   "Install LibreOffice installs a minimal copy that leaves Office's file types alone."
                   if missing == ["LibreOffice"] else
                   f"Missing: {' and '.join(missing)}. Reinstall Deck Narrator, or set DECK_NARRATOR_FFMPEG.")
        else:
            how = (f"Missing: {' and '.join(missing)} (LibreOffice draws the slides, ffmpeg makes the MP4). "
                   "Install them:  sudo apt install libreoffice-impress ffmpeg")
        self.banner_text.configure(text=how)
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
        if mode != "sample":
            self.tabs.select(self.log_tab)
        self.append("> deck-narrator " + " ".join(shlex.quote(a) for a in args))
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status.configure(text={"video": "Making the video...", "sample": "Synthesizing the sample...",
                                    "builds": "Reading the deck's animations...", "check": "Checking pronunciation..."}.get(mode, "Working..."))
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
        if line.startswith('{"issues"'):        # --check-pronunciation --json: shown in its own window
            return
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
        elif self.mode == "check":
            data = next((l for l in self.out_lines if l.startswith('{"issues"')), None)
            issues = json.loads(data)["issues"] if data else []
            self.status.configure(text=f"{len(issues)} word(s) to check." if issues else
                                  "No likely pronunciation problems found.")
            self.append(f"{len(issues)} word(s) to check, in the Check pronunciation window.")
            if getattr(self, "review", None):
                self.review.close()
            self.review = PronunciationReview(self, issues, self.v["deck"].get())
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
    opens the window, presses the button for MODE (video, builds, check, phonemes, sample)
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
