#!/usr/bin/env python3
"""
SnagIt by Echo404
A simple YouTube downloader: playlist, single video, or MP3.

Requirements:
  pip install -U "yt-dlp[default]"     (includes yt-dlp-ejs, the YouTube challenge solver)
  FFmpeg installed and on PATH         (needed for merging and mp3 conversion)
  A JavaScript runtime: deno (recommended), node, or bun
                                       (YouTube needs it or some formats go missing)

Run:
  python snagit.py                      interactive menu
  python snagit.py URL -q 720           one-liner (see: python snagit.py --help)
  python snagit.py -s lofi beats        search YouTube and watch in VLC/mpv

Optional (for search thumbnails):
  pip install Pillow
"""

import argparse
import importlib.util
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.request

if os.name == "nt":
    import msvcrt
else:
    import select
    import termios
    import tty

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None
    HAS_PIL = False

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    yt_dlp = None
    HAS_YTDLP = False

VERSION = "1.2.0"
TWITTER = "@JeffreyPeter_"
QUALITIES = ("360", "480", "720", "1080")
DEFAULT_QUALITY = "720"
VERBOSE = False  # False = clean progress only, True = full yt-dlp output
# Saves to ~/Downloads/SnagIt (works on Windows, Linux and macOS)
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "SnagIt")
RANGE_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")

# JS runtimes yt-dlp can use, in order of preference
JS_RUNTIMES = ("deno", "node", "bun")

OS = platform.system()  # "Windows", "Linux", "Darwin" (macOS)
DENO_BIN = os.path.join(os.path.expanduser("~"), ".deno", "bin")

JACK = "[JACK]"      # not installed
ALRIGHT = "[ALRIGHT]"  # installed

BANNER_LINES = [
    "███████╗███╗   ██╗ █████╗  ██████╗ ██╗████████╗",
    "██╔════╝████╗  ██║██╔══██╗██╔════╝ ██║╚══██╔══╝",
    "███████╗██╔██╗ ██║███████║██║  ███╗██║   ██║   ",
    "╚════██║██║╚██╗██║██╔══██║██║   ██║██║   ██║   ",
    "███████║██║ ╚████║██║  ██║╚██████╔╝██║   ██║   ",
    "╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝ ╚═════╝ ╚═╝   ╚═╝   ",
]

# plain fallback for terminals that can't show block characters
BANNER_FALLBACK = r"""
  ____                    ___ _
 / ___| _ __   __ _  __ _|_ _| |_
 \___ \| '_ \ / _` |/ _` || || __|
  ___) | | | | (_| | (_| || || |_
 |____/|_| |_|\__,_|\__, |___|\__|
                    |___/
"""

# RGB gradient (start -> end), edit these two to change the banner colors
GRADIENT_START = (0, 224, 255)    # cyan
GRADIENT_END = (255, 60, 200)     # magenta


# ---------- requirements check ----------

def find_js_runtime():
    """Returns (name, path) of the first JS runtime found, or (None, None)."""
    # also look in ~/.deno/bin, where the Linux/macOS installer puts deno
    search_path = os.pathsep.join([os.environ.get("PATH", ""), DENO_BIN])
    for name in JS_RUNTIMES:
        path = shutil.which(name, path=search_path)
        if path:
            return name, path
    return None, None


def deno_install_plan():
    """Picks the right Deno install method for this OS.
    Returns (display_text, args, use_shell) or None if it can't auto-install."""
    if OS == "Windows":
        if shutil.which("winget"):
            cmd = ["winget", "install", "--id", "DenoLand.Deno", "-e",
                   "--accept-source-agreements", "--accept-package-agreements"]
            return "winget install DenoLand.Deno", cmd, False
        cmd = ["powershell", "-NoProfile", "-Command", "irm https://deno.land/install.ps1 | iex"]
        return "PowerShell: irm https://deno.land/install.ps1 | iex", cmd, False
    if OS in ("Linux", "Darwin"):
        missing = [t for t in ("curl", "unzip") if shutil.which(t) is None]
        if missing:
            print(f"  Deno's installer needs: {', '.join(missing)}")
            if OS == "Linux":
                print(f"  Install them first: sudo apt install {' '.join(missing)}\n")
            return None
        cmd = "curl -fsSL https://deno.land/install.sh | sh -s -- -y"
        return cmd, cmd, True
    return None


def js_install_hint():
    """Short one-line hint shown in the requirements checklist."""
    if OS == "Windows":
        return "winget install DenoLand.Deno  (or install Node.js)"
    if OS == "Linux":
        return "curl -fsSL https://deno.land/install.sh | sh  (or: sudo apt install nodejs)"
    if OS == "Darwin":
        return "brew install deno  (or: brew install node)"
    return "install deno or node from their websites"


def offer_js_install():
    """Asks the user, then installs Deno using the method that fits their OS."""
    plan = deno_install_plan()
    if plan is None:
        return
    display, args, use_shell = plan
    print(f"  Detected OS: {OS}")
    print(f"  I can install Deno for you with: {display}")
    if input("  Install Deno now? (y/n): ").strip().lower() != "y":
        print()
        return
    print()
    try:
        result = subprocess.run(args, shell=use_shell)
    except Exception as e:
        print(f"\n  Install failed: {e}\n")
        return
    if result.returncode != 0:
        print("\n  Install didn't finish cleanly. Try the command above manually.\n")
        return
    name, _ = find_js_runtime()
    if name:
        print(f"\n  {ALRIGHT} JS runtime ({name}) is ready.\n")
    else:
        print("\n  Installed, but it isn't on PATH for this session yet.")
        print("  Close this terminal, open a new one, and run SnagIt again.\n")
        if OS == "Linux":
            print('  If it still isn\'t found: export PATH="$HOME/.deno/bin:$PATH"\n')


def check_requirements(verbose=True):
    """Prints the requirements checklist. Returns the JS runtime found (or None).
    With verbose=False (one-liner mode) only the warnings are printed."""
    js_name, js_path = find_js_runtime()
    has_ejs = importlib.util.find_spec("yt_dlp_ejs") is not None

    checks = [
        ("yt-dlp", HAS_YTDLP, 'pip install -U "yt-dlp[default]"'),
        ("yt-dlp-ejs (challenge solver)", has_ejs, 'pip install -U "yt-dlp[default]"'),
        ("FFmpeg", shutil.which("ffmpeg") is not None, "https://ffmpeg.org/download.html"),
        (
            f"JS runtime ({js_name})" if js_name else "JS runtime (deno/node/bun)",
            js_name is not None,
            js_install_hint(),
        ),
        ("Media player (VLC / mpv, for search)", any(find_player(n) for n in PLAYER_SPECS),
         "install VLC (videolan.org) or mpv (mpv.io)"),
        ("Pillow (search thumbnails, optional)", HAS_PIL, "pip install Pillow"),
    ]

    if verbose:
        print("  Requirements:")
        for label, ok, fix in checks:
            print(f"  {ALRIGHT if ok else JACK:<10} {label}")
            if not ok:
                print(f"             -> {fix}")
        print()

    if not HAS_YTDLP:
        sys.exit("yt-dlp is required. Install it first, then run SnagIt again.")

    if not (js_name and has_ejs):
        print("[!] Without a JS runtime + yt-dlp-ejs, YouTube may hide formats")
        print('    and you can get "Requested format is not available".\n')
    if shutil.which("ffmpeg") is None:
        print("[!] Without FFmpeg, merging and MP3 conversion will fail.\n")

    return js_name


def print_banner():
    """Prints the SnagIt banner with a diagonal RGB gradient (plain if colors are off)."""
    try:
        "█╗║╔═╝╚".encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        print(BANNER_FALLBACK)
        return
    use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    if not use_color:
        print("\n" + "\n".join(BANNER_LINES) + "\n")
        return
    if OS == "Windows":
        os.system("")  # switches on ANSI colors in the Windows console
    rows, cols = len(BANNER_LINES), max(len(l) for l in BANNER_LINES)
    out = []
    for r, line in enumerate(BANNER_LINES):
        chars = []
        for c, ch in enumerate(line):
            if ch == " ":
                chars.append(ch)
                continue
            t = (c / cols) * 0.75 + (r / rows) * 0.25   # mostly left -> right, slightly top -> bottom
            rgb = [round(a + (b - a) * t) for a, b in zip(GRADIENT_START, GRADIENT_END)]
            chars.append(f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{ch}")
        out.append("".join(chars) + "\033[0m")
    print("\n" + "\n".join(out) + "\n")


def welcome():
    print_banner()
    print("  Welcome to SnagIt by Echo404")
    print(f"  Twitter: {TWITTER}")
    print("  " + "-" * 30 + "\n")
    js_name = check_requirements()
    if js_name is None:
        offer_js_install()
        js_name, _ = find_js_runtime()
    return js_name


# ---------- input helpers ----------

def ask_choice(prompt, options):
    """options: list of (key, label). Returns the chosen key."""
    print(prompt)
    for i, (_, label) in enumerate(options, 1):
        print(f"  {i}) {label}")
    while True:
        raw = input(f"Choose 1-{len(options)}: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            print()
            return options[int(raw) - 1][0]
        print("Invalid choice, try again.")


def ask_link():
    while True:
        url = input("Paste the link: ").strip()
        if url.startswith("http"):
            print()
            return url
        print("That doesn't look like a valid link.")


def ask_quality():
    return ask_choice("Select quality:", [(q, f"{q}p") for q in QUALITIES])


def valid_range(text):
    if not RANGE_RE.match(text):
        return False
    for part in text.split(","):
        if "-" in part:
            a, b = map(int, part.split("-"))
            if a < 1 or b < a:
                return False
        elif int(part) < 1:
            return False
    return True


def ask_range():
    """Returns None for 'all', otherwise a yt-dlp playlist_items string."""
    while True:
        raw = input('Range (e.g. 1-5,8,10-12) or "all": ').strip().lower().replace(" ", "")
        if raw in ("all", ""):
            print()
            return None
        if valid_range(raw):
            print()
            return raw
        print('Invalid range. Use something like 5-20, 1-5,8,10-12, or "all".')


# ---------- yt-dlp options ----------

def base_options(playlist, items):
    if playlist:
        template = f"{OUTPUT_DIR}/%(playlist_title|Playlist)s/%(playlist_index|0)03d - %(title)s.%(ext)s"
    else:
        template = f"{OUTPUT_DIR}/%(title)s.%(ext)s"
    opts = {
        "outtmpl": template,
        "noplaylist": not playlist,
        "ignoreerrors": True,  # skip private/deleted videos
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "windowsfilenames": True,
    }
    if playlist and items:
        opts["playlist_items"] = items
    # Tell yt-dlp which JS runtime to use (deno is on by default, node/bun are not)
    js_name, js_path = find_js_runtime()
    if js_name:
        opts["js_runtimes"] = {js_name: {"path": js_path}}
    return opts


def video_options(quality, playlist, items):
    opts = base_options(playlist, items)
    # Sort by closeness to the chosen height instead of a hard cap, so a video
    # that lacks the exact quality falls back to the nearest one instead of failing.
    # "res" is the smaller of width/height, so vertical Shorts get picked correctly.
    opts["format"] = "bv*+ba/b"
    opts["format_sort"] = [f"res:{quality}", "ext:mp4:m4a"]
    opts["merge_output_format"] = "mp4"
    return opts


def mp3_options(playlist, items):
    opts = base_options(playlist, items)
    opts["format"] = "bestaudio/best"
    opts["postprocessors"] = [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "192",
    }]
    return opts


# ---------- clean (non-verbose) output ----------

def fmt_size(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024


def fmt_eta(sec):
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


class CleanUI:
    """Compact output: a header line per video, a live progress bar, then a result line."""

    def __init__(self):
        try:
            "█░✓✗".encode(sys.stdout.encoding or "utf-8")
            self.full, self.empty, self.ok, self.bad = "█", "░", "✓", "✗"
        except (UnicodeEncodeError, LookupError):
            self.full, self.empty, self.ok, self.bad = "#", "-", "OK", "x"
        self.tty = sys.stdout.isatty()
        self.current = None      # id of the video being shown
        self.state = None        # None (in progress), "done" or "failed"
        self.bar_active = False
        self.done_count = 0
        self.failed_count = 0

    def _width(self):
        return shutil.get_terminal_size((80, 20)).columns - 1

    def _clear_bar(self):
        if self.bar_active:
            sys.stdout.write("\r" + " " * self._width() + "\r")
            self.bar_active = False

    def _mark_done(self):
        self._clear_bar()
        print(f"  {self.ok} Saved")
        self.done_count += 1
        self.state = "done"

    def finish(self):
        """Closes the last video if nothing else did."""
        if self.current is not None and self.state is None:
            self._mark_done()

    def begin(self, info):
        key = info.get("id") or info.get("title")
        if key == self.current:
            return
        self.finish()
        self.current, self.state = key, None
        idx = info.get("playlist_index")
        total = info.get("n_entries") or info.get("playlist_count")
        prefix = f"[{idx}/{total}] " if idx and total else (f"[{idx}] " if idx else "")
        print(f"{prefix}{info.get('title') or key}")

    def error(self, msg):
        self._clear_bar()
        msg = re.sub(r"^ERROR:\s*", "", str(msg)).strip()
        print(f"  {self.bad} {msg}")
        if self.current is not None and self.state is None:
            self.state = "failed"
            self.failed_count += 1

    # yt-dlp hooks
    def progress(self, d):
        info = d.get("info_dict") or {}
        if d.get("status") not in ("downloading", "finished"):
            return
        self.begin(info)  # 'finished' also covers files that already existed
        if d["status"] != "downloading" or not self.tty:
            return

        got = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        frac = got / total if total else None
        if frac is None and d.get("fragment_count"):
            frac = (d.get("fragment_index") or 0) / d["fragment_count"]
        frac = min(max(frac, 0.0), 1.0) if frac is not None else None

        if info.get("vcodec") not in (None, "none"):
            kind = "video"
        elif info.get("acodec") not in (None, "none"):
            kind = "audio"
        else:
            kind = ""

        n = 24
        if frac is None:
            bar, pct = self.empty * n, f"{fmt_size(got):>7}"
        else:
            filled = int(frac * n)
            bar, pct = self.full * filled + self.empty * (n - filled), f"{frac * 100:5.1f}%"
        speed = f"{fmt_size(d['speed'])}/s" if d.get("speed") else ""
        eta = f"ETA {fmt_eta(d['eta'])}" if d.get("eta") is not None else ""
        line = f"  {kind:<5} {bar} {pct}  {speed:>10}  {eta}"
        sys.stdout.write("\r" + line.ljust(self._width())[:self._width()])
        sys.stdout.flush()
        self.bar_active = True

    def post(self, d):
        if d.get("postprocessor") == "MoveFiles" and d.get("status") == "finished":
            if self.current is not None and self.state is None:
                self._mark_done()


class CleanLogger:
    """Swallows yt-dlp's own messages; only errors are shown (through CleanUI)."""

    def __init__(self, ui):
        self.ui = ui

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): self.ui.error(msg)


def run(url, opts):
    print("Snagging... \n")
    ui = None
    if not VERBOSE:
        ui = CleanUI()
        opts.update(
            quiet=True, no_warnings=True, noprogress=True,
            logger=CleanLogger(ui),
            progress_hooks=[ui.progress],
            postprocessor_hooks=[ui.post],
        )
    with yt_dlp.YoutubeDL(opts) as ydl:
        code = ydl.download([url])

    if ui:
        ui.finish()
        summary = f"{ui.done_count} saved"
        if ui.failed_count:
            summary += f", {ui.failed_count} failed"
        print(f"\nDone! {summary}. Files in {OUTPUT_DIR}")
        return 1 if ui.failed_count else code
    if code:
        print("\nSomething failed, check the messages above. Nothing (or not everything) was saved.")
    else:
        print(f"\nDone! Files saved in {OUTPUT_DIR}")
    return code


# ---------- search & watch (browse YouTube results in the terminal) ----------

SEARCH_PAGE = 10             # results fetched per batch (more load as you scroll down)
SEARCH_MAX = 200             # stop loading after this many results
THUMB_W, THUMB_ROWS = 11, 3  # thumbnail size in terminal cells (1 cell = 1x2 pixels)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# dual = the player can take a separate video + audio stream (higher quality online).
# Players without it get a single combined stream (usually up to 720p).
PLAYER_SPECS = {
    "vlc": {"bins": ("vlc",), "dual": True},
    "mpv": {"bins": ("mpv",), "dual": True},
    "iina": {"bins": ("iina-cli",), "dual": False},   # macOS
    "ffplay": {"bins": ("ffplay",), "dual": False},   # ships with FFmpeg
}


def player_paths(name):
    """Common install locations for players that aren't always on PATH."""
    if name == "vlc":
        paths = ["/Applications/VLC.app/Contents/MacOS/VLC"]
        for var in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(var)
            if base:
                paths.append(os.path.join(base, "VideoLAN", "VLC", "vlc.exe"))
        return paths
    if name == "mpv":
        return ["/opt/homebrew/bin/mpv", "/usr/local/bin/mpv"]
    if name == "iina":
        return ["/Applications/IINA.app/Contents/MacOS/iina-cli"]
    return []


def find_player(name):
    """Returns the executable path for a player name (or a custom command/path), else None."""
    spec = PLAYER_SPECS.get(name)
    if spec:
        for b in spec["bins"]:
            path = shutil.which(b)
            if path:
                return path
        for path in player_paths(name):
            if os.path.isfile(path):
                return path
        return None
    return shutil.which(name) or (name if os.path.isfile(name) else None)


def available_players(preferred=None):
    names = [n for n in PLAYER_SPECS if find_player(n)]
    if preferred and preferred not in names:
        if find_player(preferred):
            names.insert(0, preferred)   # a custom player given with -P
        else:
            print(f"Player '{preferred}' was not found on this system, ignoring it.\n")
    return names


def config_path():
    if OS == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "snagit", "config.json")


def load_config():
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(config_path()), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


def pick_default_player(names, preferred=None):
    if preferred in names:
        return preferred
    saved = load_config().get("player")
    if saved in names:
        return saved
    return names[0] if names else None


class QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def short_error(ex):
    text = ANSI_RE.sub("", str(ex)).strip()
    text = re.sub(r"^ERROR:\s*", "", text)
    return (text.splitlines() or [type(ex).__name__])[0][:150]


def resolve_stream(url, quality, dual):
    """Asks yt-dlp for direct stream URLs. Returns (title, video_url, audio_url or None)."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": QuietLogger()}
    if dual:
        opts["format"] = "bv*+ba/b"
        opts["format_sort"] = [f"res:{quality}", "ext:mp4:m4a"]
    else:
        opts["format"] = "b[acodec!=none][vcodec!=none]/b"
        opts["format_sort"] = [f"res:{quality}"]
    js_name, js_path = find_js_runtime()
    if js_name:
        opts["js_runtimes"] = {js_name: {"path": js_path}}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    fmts = info.get("requested_formats") or [info]
    has_v = lambda f: f.get("vcodec") not in (None, "none")
    has_a = lambda f: f.get("acodec") not in (None, "none")
    video = next((f for f in fmts if has_v(f)), fmts[0])
    audio = next((f for f in fmts if not has_v(f) and has_a(f)), None)
    return info.get("title") or url, video["url"], (audio["url"] if audio else None)


def build_player_cmd(name, exe, title, video_url, audio_url):
    if name == "vlc":
        cmd = [exe]
        if audio_url:
            cmd.append("--input-slave=" + audio_url)
        return cmd + ["--meta-title=" + title, video_url]
    if name == "mpv":
        cmd = [exe, "--ytdl=no", "--force-media-title=" + title]
        if audio_url:
            cmd.append("--audio-file=" + audio_url)
        return cmd + [video_url]
    if name == "ffplay":
        return [exe, "-autoexit", "-window_title", title, video_url]
    return [exe, video_url]   # iina and any custom player: just hand it the URL


def launch_detached(cmd):
    """Starts the player on its own so the list stays usable while it plays."""
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if OS == "Windows":
        kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


# --- terminal helpers ---

def detect_truecolor():
    if OS == "Windows" or os.environ.get("WT_SESSION"):
        return True
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return True
    return os.environ.get("TERM_PROGRAM") in ("iTerm.app", "vscode", "WezTerm", "ghostty")


def rgb256(r, g, b):
    """Nearest color in the 256-color palette (for terminals without truecolor)."""
    if abs(r - g) < 10 and abs(g - b) < 10:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round((r - 8) / 247 * 24) + 232
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def render_thumb(data, truecolor):
    """Turns image bytes into THUMB_ROWS strings of half-block characters (2 pixels per cell)."""
    resample = getattr(Image, "Resampling", Image).LANCZOS
    img = Image.open(io.BytesIO(data)).convert("RGB").resize((THUMB_W, THUMB_ROWS * 2), resample)
    px = img.load()

    def color(kind, rgb):
        if truecolor:
            return f"\033[{kind};2;{rgb[0]};{rgb[1]};{rgb[2]}m"
        return f"\033[{kind};5;{rgb256(*rgb)}m"

    rows = []
    for r in range(THUMB_ROWS):
        cells = [color(38, px[c, 2 * r]) + color(48, px[c, 2 * r + 1]) + "▀" for c in range(THUMB_W)]
        rows.append("".join(cells) + "\033[0m")
    return rows


def char_w(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def fit(text, width):
    """Clips text to `width` terminal cells (wide characters count as 2). Returns (text, used)."""
    total = sum(char_w(c) for c in text)
    if total <= width:
        return text, total
    out, used = [], 0
    for ch in text:
        cw = char_w(ch)
        if used + cw > width - 1:
            break
        out.append(ch)
        used += cw
    return "".join(out) + "…", used + 1


def fmt_duration(sec):
    if not sec:
        return "--:--"
    h, rest = divmod(int(sec), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_views(n):
    if n is None:
        return ""
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.1f}{suffix}".replace(".0", "") + " views"
    return f"{int(n)} views"


class Terminal:
    """Single-key input on an alternate screen (like `less`). Windows, Linux and macOS."""

    # longest first, so "[5~" is tried before shorter ones
    SEQS = sorted({
        "[A": "up", "OA": "up", "[B": "down", "OB": "down",
        "[5~": "pgup", "[6~": "pgdn",
        "[H": "home", "OH": "home", "[1~": "home", "[7~": "home",
        "[F": "end", "OF": "end", "[4~": "end", "[8~": "end",
    }.items(), key=lambda kv: -len(kv[0]))
    WIN_KEYS = {"H": "up", "P": "down", "I": "pgup", "Q": "pgdn", "G": "home", "O": "end"}

    def __init__(self):
        self.buf = ""

    def __enter__(self):
        try:
            sys.stdout.reconfigure(errors="replace")   # odd characters in titles never crash the UI
        except (AttributeError, ValueError):
            pass
        if OS == "Windows":
            os.system("")   # switches on ANSI colors in the Windows console
        else:
            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
        sys.stdout.write("\033[?1049h\033[?25l\033[?7l\033[2J")   # alt screen, hide cursor, no wrap
        sys.stdout.flush()
        return self

    def __exit__(self, *exc):
        sys.stdout.write("\033[0m\033[?7h\033[?25h\033[?1049l")
        sys.stdout.flush()
        if OS != "Windows":
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    @staticmethod
    def _norm(ch):
        if ch in ("\r", "\n"):
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\x03":      # Ctrl+C (Windows returns it as a plain key)
            return "q"
        if ch == "\x1b":
            return "esc"
        return ch if ch.isprintable() else "other"

    def _parse(self):
        b = self.buf
        if b[0] == "\x1b":
            rest = b[1:]
            if not rest:
                self.buf = ""
                return "esc"
            for seq, name in self.SEQS:
                if rest.startswith(seq):
                    self.buf = rest[len(seq):]
                    return name
            m = re.match(r"[\[O][0-9;]*[A-Za-z~]", rest)
            self.buf = rest[m.end():] if m else rest
            return "other"
        self.buf = b[1:]
        return self._norm(b[0])

    def poll_key(self, timeout=0.1):
        """Returns a key name ('up', 'down', 'enter', 'q', ...) or None if nothing was pressed."""
        if self.buf:
            return self._parse()
        if OS == "Windows":
            end = time.time() + timeout
            while time.time() < end:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\x00", "\xe0"):
                        return self.WIN_KEYS.get(msvcrt.getwch(), "other")
                    return self._norm(ch)
                time.sleep(0.02)
            return None
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return None
        self.buf += os.read(self.fd, 64).decode("utf-8", "ignore")
        return self._parse() if self.buf else None


# --- the results browser ---

class SearchSession:
    """Holds the search results, cursor position and background loaders."""

    def __init__(self, query, quality, players, player, thumbs):
        self.query = query
        self.quality = quality
        self.players = players
        self.player = player
        self.use_thumbs = thumbs
        self.truecolor = detect_truecolor()
        self.results, self.seen = [], set()
        self.thumbs = {}                       # video id -> rendered lines (None if it failed)
        self.thumb_slots = threading.Semaphore(6)
        self.cursor = self.top = 0
        self.vis = 1                           # items that fit on screen (set when drawing)
        self.loading = self.exhausted = False
        self.lock = threading.Lock()
        self.status = ""
        self.version = 0                       # bumped whenever something changes, triggers a redraw

    def touch(self):
        self.version += 1

    def set_status(self, msg):
        self.status = msg
        self.touch()

    # -- loading results --

    def ensure_more(self):
        """Starts loading the next batch when you get near the end of the list."""
        with self.lock:
            if self.loading or self.exhausted or len(self.results) >= SEARCH_MAX:
                return
            if self.results and self.cursor < len(self.results) - 3:
                return
            self.loading = True
            want = len(self.results) + SEARCH_PAGE
        threading.Thread(target=self._fetch, args=(want,), daemon=True).start()
        self.touch()

    def _fetch(self, want):
        entries, failed = [], False
        try:
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                    "skip_download": True, "logger": QuietLogger()}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{want}:{self.query}", download=False)
                entries = [e for e in ((info or {}).get("entries") or []) if e and e.get("id")]
        except Exception as ex:
            failed = True
            self.status = f"Search failed: {short_error(ex)}  (press r to retry)"
        added = []
        with self.lock:
            for e in entries:
                if e["id"] in self.seen:
                    continue
                self.seen.add(e["id"])
                vid = e["id"]
                added.append({
                    "id": vid,
                    "title": CONTROL_RE.sub(" ", e.get("title") or vid),
                    "channel": CONTROL_RE.sub(" ", e.get("channel") or e.get("uploader") or ""),
                    "duration": e.get("duration"),
                    "views": e.get("view_count"),
                    "live": e.get("live_status") in ("is_live", "is_upcoming"),
                    "url": e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={vid}",
                })
            self.results.extend(added)
            if failed or not added:
                self.exhausted = True          # nothing new to show; 'r' tries again
            self.loading = False
        for entry in added:
            self._start_thumb(entry["id"])
        self.touch()

    def retry(self):
        with self.lock:
            self.exhausted = False
        self.set_status("Retrying...")
        self.ensure_more()

    # -- thumbnails --

    def _start_thumb(self, vid):
        if self.use_thumbs:
            threading.Thread(target=self._load_thumb, args=(vid,), daemon=True).start()

    def _load_thumb(self, vid):
        with self.thumb_slots:
            try:
                req = urllib.request.Request(f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                                             headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    self.thumbs[vid] = render_thumb(resp.read(), self.truecolor)
            except Exception:
                self.thumbs[vid] = None
        self.touch()

    # -- player --

    def cycle_player(self):
        if not self.players:
            self.set_status("No media player found. Install VLC or mpv (or use -P).")
            return
        i = self.players.index(self.player) if self.player in self.players else -1
        self.player = self.players[(i + 1) % len(self.players)]
        cfg = load_config()
        cfg["player"] = self.player
        save_config(cfg)
        self.set_status(f"Player: {self.player}")

    def cycle_quality(self):
        i = QUALITIES.index(self.quality) if self.quality in QUALITIES else 0
        self.quality = QUALITIES[(i + 1) % len(QUALITIES)]
        self.set_status(f"Watch quality: {self.quality}p")

    def play(self, entry):
        if not self.player:
            self.set_status("No media player found. Install VLC or mpv (or use -P).")
            return
        exe = find_player(self.player)
        if not exe:
            self.set_status(f"Can't find {self.player} anymore. Press p to switch player.")
            return
        threading.Thread(target=self._play, args=(entry, self.player, exe, self.quality),
                         daemon=True).start()

    def _play(self, entry, name, exe, quality):
        self.set_status(f"Getting stream: {entry['title']}")
        try:
            dual = PLAYER_SPECS.get(name, {}).get("dual", False)
            title, video_url, audio_url = resolve_stream(entry["url"], quality, dual)
            proc = launch_detached(build_player_cmd(name, exe, title, video_url, audio_url))
            time.sleep(1.5)
            code = proc.poll()
            if code not in (None, 0):
                self.set_status(f"{name} closed right away (exit code {code}). Try another player with p.")
            else:
                self.set_status(f"Playing in {name}: {title}")
        except Exception as ex:
            self.set_status(f"Could not play: {short_error(ex)}")


def render_item(s, i, cols):
    """The lines for one result: thumbnail on the left, title / channel info / link on the right."""
    e = s.results[i]
    selected = i == s.cursor
    thumbs = s.use_thumbs
    n_rows = THUMB_ROWS if thumbs else 2
    text_w = max(cols - 2 - ((THUMB_W + 2) if thumbs else 0), 10)
    meta = " | ".join(b for b in (e["channel"], "LIVE" if e["live"] else fmt_duration(e["duration"]),
                                  fmt_views(e["views"])) if b)
    texts = [f"{i + 1}. {e['title']}", meta, e["url"]]
    if thumbs:
        art = s.thumbs.get(e["id"])
        if not art:   # still loading (or failed): grey placeholder
            art = ["\033[48;5;238m" + " " * THUMB_W + "\033[0m"] * THUMB_ROWS
    lines = []
    for r in range(n_rows):
        marker = "\033[1;36m>\033[0m " if selected and r == 0 else "  "
        left = marker + (art[r] + "  " if thumbs else "")
        txt, used = fit(texts[r], text_w)
        if selected and r < 2:
            txt = f"\033[7m{txt}{' ' * (text_w - used)}\033[0m"
        elif r == 0:
            txt = f"\033[1m{txt}\033[0m"
        elif r == 2:
            txt = f"\033[2m{txt}\033[0m"
        lines.append(left + txt)
    return lines


def build_frame(s):
    cols, rows = shutil.get_terminal_size((80, 24))
    n_rows = THUMB_ROWS if s.use_thumbs else 2
    item_h = n_rows + 1                        # one blank line between videos
    body_rows = max(rows - 4, item_h)
    s.vis = max(body_rows // item_h, 1)
    total = len(s.results)
    s.cursor = max(0, min(s.cursor, total - 1)) if total else 0
    if s.cursor < s.top:
        s.top = s.cursor
    if s.cursor >= s.top + s.vis:
        s.top = s.cursor - s.vis + 1

    # header bar
    right = f" player: {s.player or 'none'} | quality: {s.quality}p "
    left, used = fit(f" SnagIt search: {s.query}", max(cols - len(right), 10))
    header = f"\033[7m{left}{' ' * max(cols - used - len(right), 0)}{right}\033[0m"
    lines = [header, "-" * cols]

    # results
    body = []
    for i in range(s.top, min(s.top + s.vis, total)):
        body.extend(render_item(s, i, cols))
        body.append("")
    if not total:
        body.append("  Searching..." if s.loading else "  No results.")
    elif s.loading and s.top + s.vis >= total:
        body.append("  Loading more...")
    body = body[:body_rows]
    body += [""] * (body_rows - len(body))
    lines.extend(body)

    # footer
    pos = f"{min(s.cursor + 1, total)}/{total}{'' if s.exhausted else '+'}"
    status, _ = fit(f" {pos}   {s.status}", cols)
    keys, _ = fit(" Up/Down move | Enter watch | p player | u quality | d download | m mp3 | / search | q quit",
                  cols)
    lines += [status, f"\033[2m{keys}\033[0m"]
    return "\033[H" + "\033[K\n".join(lines) + "\033[K\033[J"


def browse(s, term):
    """Runs the list until the user picks an action. Returns (action, entry)."""
    last_version, last_size = -1, None
    s.ensure_more()
    while True:
        size = shutil.get_terminal_size()
        if s.version != last_version or size != last_size:
            last_version = s.version
            if size != last_size and last_size is not None:
                sys.stdout.write("\033[2J")
            last_size = size
            sys.stdout.write(build_frame(s))
            sys.stdout.flush()
        key = term.poll_key(0.1)
        s.ensure_more()
        if key is None:
            continue
        n = len(s.results)
        last = max(n - 1, 0)
        if key in ("q", "esc"):
            return "quit", None
        elif key in ("down", "j"):
            s.cursor = min(s.cursor + 1, last)
        elif key in ("up", "k"):
            s.cursor = max(s.cursor - 1, 0)
        elif key in ("pgdn", "space", "f"):
            s.cursor = min(s.cursor + s.vis, last)
        elif key in ("pgup", "b"):
            s.cursor = max(s.cursor - s.vis, 0)
        elif key in ("home", "g"):
            s.cursor = 0
        elif key in ("end", "G"):
            s.cursor = last
        elif key == "enter" and n:
            s.play(s.results[s.cursor])
        elif key == "p":
            s.cycle_player()
        elif key == "u":
            s.cycle_quality()
        elif key == "r":
            s.retry()
        elif key == "/":
            return "search", None
        elif key in ("d", "m") and n:
            return ("download" if key == "d" else "mp3"), s.results[s.cursor]
        s.touch()


def search_flow(query, quality=None, player=None, thumbs=True):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("Search mode needs an interactive terminal.")
    players = available_players(player)
    current = pick_default_player(players, player)
    quality = quality or DEFAULT_QUALITY
    try:
        "▀".encode(sys.stdout.encoding or "utf-8")
        encodable = True
    except (UnicodeEncodeError, LookupError):
        encodable = False
    use_thumbs = thumbs and HAS_PIL and encodable and "NO_COLOR" not in os.environ

    def new_session(q):
        s = SearchSession(q, quality, players, current, use_thumbs)
        if thumbs and not use_thumbs:
            s.status = "Thumbnails off (install Pillow: pip install Pillow)" if not HAS_PIL else "Thumbnails off"
        if not players:
            s.status = "No media player found. Install VLC or mpv, or use -P /path/to/player"
        return s

    session = new_session(query)
    while True:
        with Terminal() as term:
            action, entry = browse(session, term)
        quality, current = session.quality, session.player
        if action == "quit":
            return 0
        if action == "search":
            text = input("Search YouTube (empty = back to the list): ").strip()
            if text:
                session = new_session(text)
            continue
        try:
            if action == "download":
                print(f"\n{entry['title']}\n")
                run(entry["url"], video_options(ask_quality(), False, None))
            else:
                print(f"\n{entry['title']}\n")
                run(entry["url"], mp3_options(False, None))
        except KeyboardInterrupt:
            print("\nCancelled.")
        except Exception as e:
            print(f"\nError: {e}")
        input("\nPress Enter to go back to the list...")


def search_main(args):
    global VERBOSE, OUTPUT_DIR
    VERBOSE = args.verbose
    if not HAS_YTDLP:
        sys.exit("yt-dlp is required. Install it: pip install -U \"yt-dlp[default]\"")
    check_requirements(verbose=False)
    if args.output:
        OUTPUT_DIR = os.path.abspath(os.path.expanduser(args.output))
    query = " ".join(args.search).strip()
    if not query:
        sys.exit("snagit: the search text is empty")
    return search_flow(query, args.quality, args.player, not args.no_thumbs)


def flow_search():
    query = ""
    while not query:
        query = input("Search YouTube: ").strip()
    print()
    search_flow(query)


# ---------- flows ----------

def flow_playlist():
    url = ask_link()
    quality = ask_quality()
    items = ask_range()
    run(url, video_options(quality, True, items))


def flow_single():
    url = ask_link()
    quality = ask_quality()
    run(url, video_options(quality, False, None))


def flow_mp3():
    kind = ask_choice("MP3 from:", [("single", "Single video"), ("playlist", "Playlist")])
    url = ask_link()
    if kind == "playlist":
        items = ask_range()
        run(url, mp3_options(True, items))
    else:
        run(url, mp3_options(False, None))


def interactive_main(verbose=None):
    global VERBOSE
    welcome()
    if verbose is None:
        style = ask_choice(
            "Output style:",
            [("clean", "Clean (just progress and video names)"),
             ("verbose", "Verbose (full yt-dlp messages)")],
        )
        VERBOSE = style == "verbose"
    else:
        VERBOSE = verbose
    while True:
        choice = ask_choice(
            "What do you want to snag?",
            [("playlist", "Playlist"), ("single", "Single video"), ("mp3", "MP3 (audio only)"),
             ("search", "Search YouTube & watch")],
        )
        try:
            {"playlist": flow_playlist, "single": flow_single, "mp3": flow_mp3,
             "search": flow_search}[choice]()
        except KeyboardInterrupt:
            print("\nCancelled.")
        except Exception as e:
            print(f"\nError: {e}")

        again = input("\nSnag something else? (y/n): ").strip().lower()
        if again != "y":
            print("\nThanks for using SnagIt. See you, Echo404 out ;)")
            print(f"Follow me on Twitter: {TWITTER}")
            break
        print()


# ---------- command line (one-liner) mode ----------

def range_arg(text):
    text = text.replace(" ", "")
    if not valid_range(text):
        raise argparse.ArgumentTypeError(
            f"invalid range '{text}' (use something like 5-20 or 1-5,8,10-12)")
    return text


def build_parser():
    p = argparse.ArgumentParser(
        prog="snagit",
        description="SnagIt by Echo404: download YouTube videos, playlists or MP3s. "
                    "Run with no arguments for the interactive menu.",
        epilog="examples:\n"
               "  snagit URL -q 720              single video at 720p\n"
               "  snagit URL -p -q 1080 -r 1-5   first 5 videos of a playlist\n"
               "  snagit URL -a                  single video as MP3\n"
               "  snagit URL -a -p               whole playlist as MP3\n"
               "  snagit URL -p -v               playlist with full yt-dlp output\n"
               "  snagit -s lofi hip hop         search YouTube, browse results, watch\n"
               "  snagit -s lofi -P mpv -q 1080  same, using mpv at 1080p\n\n"
               f"made by Echo404 - Twitter: {TWITTER}\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("url", nargs="?", help="video or playlist link (asked for if omitted)")
    p.add_argument("-q", "--quality", choices=QUALITIES, metavar="{" + ",".join(QUALITIES) + "}",
                   help=f"video quality in p (default: {DEFAULT_QUALITY})")
    p.add_argument("-p", "--playlist", action="store_true",
                   help="treat the link as a playlist (default: single video)")
    p.add_argument("-a", "--audio", action="store_true",
                   help="audio only, converted to MP3 (combine with -p for a playlist)")
    p.add_argument("-r", "--range", type=range_arg, metavar="RANGE",
                   help='playlist items to get, e.g. 1-5,8,10-12 (default: all; needs -p)')
    p.add_argument("-o", "--output", metavar="DIR",
                   help=f"output folder (default: {OUTPUT_DIR})")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show full yt-dlp output (default: clean progress only)")
    p.add_argument("-s", "--search", nargs="+", metavar="TEXT",
                   help="search YouTube and browse the results (Enter = watch, d = download)")
    p.add_argument("-P", "--player", metavar="NAME",
                   help="player for search mode: vlc, mpv, iina, ffplay, or any command/path "
                        "(default: last one used, else the first one found)")
    p.add_argument("-T", "--no-thumbs", action="store_true",
                   help="search mode: don't show thumbnails")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="force the interactive menu")
    p.add_argument("-V", "--version", action="version", version=f"SnagIt {VERSION}")
    return p


def cli_main(args):
    global OUTPUT_DIR, VERBOSE
    VERBOSE = args.verbose
    if not HAS_YTDLP:
        sys.exit("yt-dlp is required. Install it: pip install -U \"yt-dlp[default]\"")
    check_requirements(verbose=False)

    if args.output:
        OUTPUT_DIR = os.path.abspath(os.path.expanduser(args.output))
    if args.range and not args.playlist:
        print("Note: -r/--range only applies with -p/--playlist, ignoring it.\n")
        args.range = None
    if args.audio and args.quality:
        print("Note: -q/--quality is ignored for audio (MP3).\n")

    url = args.url
    if url is None:
        url = ask_link()
    elif not url.startswith("http"):
        sys.exit(f"snagit: '{url}' doesn't look like a valid link")

    if args.audio:
        opts = mp3_options(args.playlist, args.range)
    else:
        opts = video_options(args.quality or DEFAULT_QUALITY, args.playlist, args.range)
    return run(url, opts)


def main():
    args = build_parser().parse_args()
    if args.search is not None:
        sys.exit(search_main(args))
    if args.interactive or len(sys.argv) == 1:
        interactive_main(True if args.verbose else None)
    else:
        sys.exit(cli_main(args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")
        sys.exit(130)
