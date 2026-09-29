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
  python snagit.py -s song name -a -f   play the top result as audio only
  python snagit.py --web                local web interface (opens your browser)
  python snagit.py --web --check        ...straight to the requirements page
  python snagit.py --web --lan          also reachable from a phone on the same Wi-Fi

Web interface (--web): one box that takes a link or plain text.
  paste https://youtube.com/playlist?list=...   -> checklist of the playlist; tick videos,
                                                   pick 720p or MP3, press Download, and the
                                                   terminal starts it with the usual progress
  type "yung kai blue"                          -> YouTube search results (10 at a time)
  paste a single video link                     -> one video card (Watch / Audio / Download / MP3)
  --lan: run `snagit --web --lan`, scan the QR code (or open the address), enter the PIN,
  approve the device in the terminal, then paste links or stream music from Downloads.

Optional (for search thumbnails):
  pip install Pillow
Optional (QR code for --lan):
  pip install qrcode
"""

import argparse
import http.cookies
import http.server
import hmac
import importlib.util
import io
import json
import mimetypes
import os
import platform
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import webbrowser

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

VERSION = "1.4.0"
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


def offer_js_install(ask=True):
    """Asks the user, then installs Deno using the method that fits their OS.
    ask=False skips the y/n question (the web page has its own button)."""
    plan = deno_install_plan()
    if plan is None:
        return
    display, args, use_shell = plan
    print(f"  Detected OS: {OS}")
    print(f"  I can install Deno for you with: {display}")
    if ask and input("  Install Deno now? (y/n): ").strip().lower() != "y":
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


def requirement_checks():
    """The checklist data, shared by the terminal and the web page.
    Returns (checks, js_name, has_ejs) where checks is a list of (label, ok, fix_hint)."""
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
    return checks, js_name, has_ejs


def check_requirements(verbose=True):
    """Prints the requirements checklist. Returns the JS runtime found (or None).
    With verbose=False (one-liner mode) only the warnings are printed."""
    checks, js_name, has_ejs = requirement_checks()

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


def run(url, opts, tap=None):
    """tap(kind, d) is optional: the web page uses it to mirror progress (kind is "progress" or "post")."""
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
    if tap:
        opts.setdefault("progress_hooks", []).append(lambda d: tap("progress", d))
        opts.setdefault("postprocessor_hooks", []).append(lambda d: tap("post", d))
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


def resolve_stream(url, quality, dual, audio_only=False):
    """Asks yt-dlp for direct stream URLs. Returns (title, video_url, audio_url or None)."""
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": QuietLogger()}
    if audio_only:
        opts["format"] = "bestaudio/best"
    elif dual:
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
    if audio_only:
        return info.get("title") or url, fmts[0]["url"], None
    has_v = lambda f: f.get("vcodec") not in (None, "none")
    has_a = lambda f: f.get("acodec") not in (None, "none")
    video = next((f for f in fmts if has_v(f)), fmts[0])
    audio = next((f for f in fmts if not has_v(f) and has_a(f)), None)
    return info.get("title") or url, video["url"], (audio["url"] if audio else None)


def build_player_cmd(name, exe, title, video_url, audio_url, audio_only=False):
    if name == "vlc":
        cmd = [exe]
        if audio_only:
            cmd += ["--no-video", "--play-and-exit"]
        if audio_url:
            cmd.append("--input-slave=" + audio_url)
        return cmd + ["--meta-title=" + title, video_url]
    if name == "mpv":
        cmd = [exe, "--ytdl=no", "--force-media-title=" + title]
        if audio_only:
            cmd.append("--no-video")
        if audio_url:
            cmd.append("--audio-file=" + audio_url)
        return cmd + [video_url]
    if name == "ffplay":
        cmd = [exe, "-autoexit", "-window_title", title]
        if audio_only:
            cmd.append("-nodisp")
        return cmd + [video_url]
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

    def __init__(self, query, quality, players, player, thumbs, audio_only=False):
        self.audio_only = audio_only
        self.proc = None                       # the audio player started from this list (if any)
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
        threading.Thread(target=self._play, args=(entry, self.player, exe, self.quality, self.audio_only),
                         daemon=True).start()

    def toggle_audio(self):
        self.audio_only = not self.audio_only
        self.set_status("Audio only: Enter now plays just the sound" if self.audio_only
                        else "Video mode: Enter opens the video")

    def stop(self):
        """Stops the audio started from this list. Returns True if something was playing."""
        proc, self.proc = self.proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            return True
        return False

    def _play(self, entry, name, exe, quality, audio_only):
        self.set_status(f"Getting stream: {entry['title']}")
        try:
            dual = PLAYER_SPECS.get(name, {}).get("dual", False)
            title, video_url, audio_url = resolve_stream(entry["url"], quality, dual, audio_only)
            if audio_only:
                self.stop()                    # one song at a time
            proc = launch_detached(build_player_cmd(name, exe, title, video_url, audio_url, audio_only))
            if audio_only:
                self.proc = proc
            time.sleep(1.5)
            code = proc.poll()
            if code not in (None, 0):
                self.set_status(f"{name} closed right away (exit code {code}). Try another player with p.")
            else:
                self.set_status(f"Playing {'audio' if audio_only else 'video'} in {name}: {title}")
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
    right = f" player: {s.player or 'none'} | {'audio only' if s.audio_only else f'quality: {s.quality}p'} "
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
    keys, _ = fit(" q quit | Enter play | a audio | s stop | p player | / search | d save | m mp3 | u quality",
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
        elif key == "a":
            s.toggle_audio()
        elif key == "s":
            s.set_status("Stopped." if s.stop() else "Nothing is playing from this list.")
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


def search_flow(query, quality=None, player=None, thumbs=True, audio_only=False):
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
        s = SearchSession(q, quality, players, current, use_thumbs, audio_only)
        if thumbs and not use_thumbs:
            s.status = "Thumbnails off (install Pillow: pip install Pillow)" if not HAS_PIL else "Thumbnails off"
        if not players:
            s.status = "No media player found. Install VLC or mpv, or use -P /path/to/player"
        return s

    session = new_session(query)
    try:
        while True:
            with Terminal() as term:
                action, entry = browse(session, term)
            quality, current, audio_only = session.quality, session.player, session.audio_only
            if action == "quit":
                return 0
            if action == "search":
                text = input("Search YouTube (empty = back to the list): ").strip()
                if text:
                    session.stop()
                    session = new_session(text)
                continue
            try:
                print(f"\n{entry['title']}\n")
                if action == "download":
                    run(entry["url"], video_options(ask_quality(), False, None))
                else:
                    run(entry["url"], mp3_options(False, None))
            except KeyboardInterrupt:
                print("\nCancelled.")
            except Exception as e:
                print(f"\nError: {e}")
            input("\nPress Enter to go back to the list...")
    finally:
        session.stop()   # don't leave music playing after you quit


def play_first(query, quality, player, audio_only):
    """One-liner mode: search, take the top result, play it right here (Ctrl+C to stop)."""
    players = available_players(player)
    name = pick_default_player(players, player)
    exe = find_player(name) if name else None
    if not exe:
        sys.exit("No media player found. Install VLC or mpv, or use -P /path/to/player")
    print(f'Searching "{query}"...')
    try:
        opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                "skip_download": True, "logger": QuietLogger()}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            entries = [e for e in ((info or {}).get("entries") or []) if e and e.get("id")]
        if not entries:
            sys.exit("No results.")
        e = entries[0]
        url = e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
        shown = CONTROL_RE.sub(" ", e.get("title") or e["id"])
        print(f"Playing {'audio' if audio_only else 'video'} in {name}: {shown}")
        print("(Ctrl+C to stop)\n")
        dual = PLAYER_SPECS.get(name, {}).get("dual", False)
        title, video_url, audio_url = resolve_stream(url, quality or DEFAULT_QUALITY, dual, audio_only)
    except KeyboardInterrupt:
        return 130
    except Exception as ex:
        sys.exit(f"snagit: {short_error(ex)}")
    cmd = build_player_cmd(name, exe, title, video_url, audio_url, audio_only)
    # mpv is happy in the terminal; GUI players would just spam it with log lines
    quiet = {} if name == "mpv" else dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return subprocess.call(cmd, **quiet)
    except KeyboardInterrupt:
        return 0


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
    if args.first:
        return play_first(query, args.quality, args.player, args.audio)
    return search_flow(query, args.quality, args.player, not args.no_thumbs, args.audio)


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


# ---------- web interface (--web) ----------
# A small local web UI on top of everything above. Standard library only.
# Downloads are queued and run by ONE worker thread through the normal run(), so the
# clean progress output shows in the terminal exactly like the other modes.

WEB_PORT = 8642
WEB_PLAYLIST_PAGE = 100
WEB_LAN_TIMEOUT = 30                       # idle minutes before --lan turns itself off
WEB_TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"   # 19-second video used by "Test"
AUDIO_EXTS = (".mp3", ".m4a", ".opus", ".ogg", ".oga", ".flac", ".wav", ".aac")
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov", ".m4v")
MEDIA_EXTS = AUDIO_EXTS + VIDEO_EXTS
PARTIAL_RE = re.compile(r"\.f\d+\.\w+$|\.temp\.\w+$", re.I)   # yt-dlp's unfinished pieces
EXTRA_MIME = {".m4a": "audio/mp4", ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".aac": "audio/aac",
              ".mkv": "video/x-matroska", ".webm": "video/webm", ".flac": "audio/flac"}
WEB_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; "
           "img-src 'self' https://i.ytimg.com data:; media-src 'self' https: blob:; "
           "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
QUIET_PATHS = ("/api/events", "/api/state")   # requests that don't count as "activity" for --lan-timeout

APP = None   # the WebApp instance, set by web_main()


class ApiError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


# --- small pure helpers (easy to test) ---

def compress_indices(nums):
    """[1,2,3,5,8] -> '1-3,5,8' (a yt-dlp playlist_items string)."""
    nums = sorted(set(int(n) for n in nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(out)


def safe_http_url(text):
    """Returns the text if it is a plain http(s) link, else None. Nothing else is ever accepted."""
    text = (text or "").strip()
    if not text or len(text) > 2000 or CONTROL_RE.search(text) or " " in text:
        return None
    try:
        p = urllib.parse.urlsplit(text)
        ok = p.scheme in ("http", "https") and bool(p.hostname)
    except ValueError:
        return None
    return text if ok else None


def classify_input(text):
    """What did the user type in the one box? Returns (kind, value):
    ('playlist', url) | ('video', url) | ('search', text)."""
    text = (text or "").strip()
    url = safe_http_url(text)
    if not url and re.match(r"^(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/\S+$", text, re.I):
        url = safe_http_url("https://" + text)
    if not url:
        return "search", text
    p = urllib.parse.urlsplit(url)
    qs = urllib.parse.parse_qs(p.query)
    host = (p.hostname or "").lower()
    is_yt = host == "youtu.be" or host.endswith(("youtube.com", "youtube-nocookie.com"))
    if "list" in qs or p.path.rstrip("/") == "/playlist":
        lid = (qs.get("list") or [""])[0]
        if is_yt and lid:
            return "playlist", "https://www.youtube.com/playlist?list=" + urllib.parse.quote(lid, safe="")
        return "playlist", url
    return "video", url


def lan_addresses():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # no packet is sent; just asks the OS which NIC it would use
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return [ip for ip in dict.fromkeys(ips) if not ip.startswith("127.")]


def need_ytdlp():
    if not HAS_YTDLP:
        raise ApiError("yt-dlp isn't installed. Open the Check page and press Update yt-dlp.", 503)


def probe_opts(**extra):
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "logger": QuietLogger()}
    js_name, js_path = find_js_runtime()
    if js_name:
        opts["js_runtimes"] = {js_name: {"path": js_path}}
    opts.update(extra)
    return opts


def web_search(query, offset):
    """Same yt-dlp extract_flat search SearchSession uses, 10 more results at a time."""
    need_ytdlp()
    s = SearchSession(query, DEFAULT_QUALITY, [], None, False)
    want = min(offset + SEARCH_PAGE, SEARCH_MAX)
    s._fetch(want)                                  # runs synchronously and fills s.results
    if s.status.startswith("Search failed"):
        raise ApiError(s.status, 502)
    items = s.results[offset:want]
    return {"items": items, "more": len(s.results) >= want and want < SEARCH_MAX}


def web_playlist(url, start):
    need_ytdlp()
    end = start + WEB_PLAYLIST_PAGE - 1
    opts = probe_opts(extract_flat=True, ignoreerrors=True, playlist_items=f"{start}-{end}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ApiError("Couldn't read that playlist (private, deleted, or not a playlist).", 502)
    entries = list(info.get("entries") or [])
    rows = []
    for i, e in enumerate(entries):
        if not e or not e.get("id"):
            continue
        rows.append({"index": start + i, "id": e["id"],
                     "title": CONTROL_RE.sub(" ", e.get("title") or e["id"]),
                     "duration": e.get("duration"),
                     "channel": CONTROL_RE.sub(" ", e.get("channel") or e.get("uploader") or "")})
    total = info.get("playlist_count") or info.get("n_entries")
    return {"url": url, "title": CONTROL_RE.sub(" ", info.get("title") or "Playlist"),
            "count": total, "items": rows, "has_more": len(entries) >= WEB_PLAYLIST_PAGE
            and (not total or start + len(entries) - 1 < total)}


def web_video(url):
    need_ytdlp()
    opts = probe_opts(noplaylist=True, ignore_no_formats_error=True, extract_flat="in_playlist")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info or not info.get("id"):
        raise ApiError("Couldn't read that link.", 502)
    return {"id": info["id"], "title": CONTROL_RE.sub(" ", info.get("title") or info["id"]),
            "channel": CONTROL_RE.sub(" ", info.get("channel") or info.get("uploader") or ""),
            "duration": info.get("duration"), "views": info.get("view_count"),
            "live": info.get("live_status") in ("is_live", "is_upcoming"),
            "url": info.get("webpage_url") or url}


def web_lookup(text):
    kind, value = classify_input(text)
    if not value:
        raise ApiError("Type or paste something first.")
    if kind == "search":
        r = web_search(value, 0)
        return {"kind": "search", "query": value, **r}
    if kind == "playlist":
        return {"kind": "playlist", **web_playlist(value, 1)}
    return {"kind": "video", "item": web_video(value)}


def list_downloads():
    root, out = OUTPUT_DIR, []
    if not os.path.isdir(root):
        return out
    for dirpath, _, names in os.walk(root):
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext not in MEDIA_EXTS or PARTIAL_RE.search(name):
                continue
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out.append({"path": rel, "name": name, "folder": os.path.dirname(rel), "size": st.st_size,
                        "mtime": int(st.st_mtime), "audio": ext in AUDIO_EXTS})
    out.sort(key=lambda f: -f["mtime"])
    return out[:3000]


def resolve_download_path(rel):
    """Maps a URL path under /files/ to a real file inside OUTPUT_DIR, or None (path traversal safe)."""
    rel = urllib.parse.unquote(rel)
    if not rel or "\x00" in rel or "\\" in rel or rel.startswith("/"):
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        return None
    root = os.path.realpath(OUTPUT_DIR)
    full = os.path.realpath(os.path.join(root, *parts))
    try:
        if os.path.commonpath([root, full]) != root or full == root:
            return None
    except ValueError:
        return None
    if (not os.path.isfile(full) or os.path.splitext(full)[1].lower() not in MEDIA_EXTS
            or PARTIAL_RE.search(os.path.basename(full))):
        return None
    return full


def parse_byte_range(header, size):
    """None = no usable Range header (send everything); 'bad' = unsatisfiable; else (start, end)."""
    m = re.match(r"^\s*bytes=(\d*)-(\d*)\s*$", header or "")
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    a, b = m.groups()
    if a == "":
        n = int(b)
        if n == 0:
            return "bad"
        start, end = max(size - n, 0), size - 1
    else:
        start = int(a)
        end = min(int(b), size - 1) if b else size - 1
    if size == 0 or start >= size or start > end:
        return "bad"
    return start, end


def web_check_data(app):
    checks, js_name, has_ejs = requirement_checks()

    def first_line(cmd):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=6, stdin=subprocess.DEVNULL)
            lines = (r.stdout or r.stderr).strip().splitlines()
            return lines[0].strip()[:70] if lines else ""
        except Exception:
            return ""

    detail = [""] * len(checks)
    if HAS_YTDLP:
        try:
            detail[0] = yt_dlp.version.__version__
        except Exception:
            pass
    if has_ejs:
        try:
            import importlib.metadata as md
            detail[1] = md.version("yt-dlp-ejs")
        except Exception:
            pass
    ff = shutil.which("ffmpeg")
    if ff:
        m = re.search(r"version\s+(\S+)", first_line([ff, "-version"]))
        detail[2] = m.group(1) if m else ""
    _, js_path = find_js_runtime()
    if js_path:
        detail[3] = first_line([js_path, "--version"])
    detail[4] = ", ".join(n for n in PLAYER_SPECS if find_player(n))
    if HAS_PIL:
        try:
            import PIL
            detail[5] = PIL.__version__
        except Exception:
            pass
    rows = [{"label": label, "ok": ok, "fix": fix, "detail": detail[i]}
            for i, (label, ok, fix) in enumerate(checks)]
    lan = None
    if app.lan:
        ip = app.lan_ips[0] if app.lan_ips else None
        hint = {"Windows": "Windows: choose Allow when the firewall asks about Python.",
                "Darwin": "macOS: choose Allow when asked about incoming connections."}.get(
                    OS, f"Linux: sudo ufw allow {app.port}")
        lan = {"on": app.lan_on, "address": f"http://{ip}:{app.port}/" if ip else None,
               "port": app.port, "firewall": hint}
    return {"checks": rows, "lan": lan, "python": platform.python_version(), "version": VERSION}


# --- jobs and the queue ---

class Job:
    def __init__(self, kind, label, url=None, quality=None, playlist=False, items=None, total=None, fn=None):
        self.id = 0
        self.kind, self.label, self.url = kind, label, url
        self.quality, self.playlist, self.items, self.total, self.fn = quality, playlist, items, total, fn
        self.status = "queued"          # queued | running | done | failed | cancelled
        self.cancel = False
        self.title, self.idx, self.n = "", None, total
        self.pct, self.speed, self.eta, self.phase = None, "", "", ""
        self.done, self.error, self.note = 0, "", ""

    def public(self):
        return {"id": self.id, "kind": self.kind, "label": self.label, "quality": self.quality,
                "status": self.status, "title": self.title, "idx": self.idx, "n": self.n, "pct": self.pct,
                "speed": self.speed, "eta": self.eta, "phase": self.phase, "done": self.done,
                "error": self.error, "note": self.note}


class WebApp:
    def __init__(self, port, lan, lan_timeout, start_view="home"):
        self.port, self.lan, self.lan_on, self.lan_timeout = port, lan, lan, lan_timeout
        self.start_view = start_view
        self.token = secrets.token_urlsafe(24)
        self.pin = self.new_pin()
        self.lan_ips = lan_addresses() if lan else []
        self.allowed_hosts = {"localhost", "127.0.0.1", "[::1]"}
        if lan:
            name = socket.gethostname().lower()
            self.allowed_hosts |= set(self.lan_ips) | {name, name + ".local"}
        self.lock = threading.RLock()
        self.cond = threading.Condition()
        self.version, self.last_touch = 0, 0.0
        self.jobs, self.next_id, self.q, self.current = [], 1, queue.Queue(), None
        self.paired, self.pending, self.approvals = set(), {}, queue.Queue()
        self.fails, self.global_fails = {}, []
        self.last_lan = time.time()
        self.audio_proc = None
        self.stopping = False

    # -- security --

    @staticmethod
    def new_pin():
        return f"{secrets.randbelow(10 ** 6):06d}"

    def token_ok(self, value):
        return bool(value) and hmac.compare_digest(value.encode("utf-8", "ignore"), self.token.encode())

    def host_ok(self, header):
        """Only our own names are accepted, which blocks DNS-rebinding (evil.com pointing at 127.0.0.1)."""
        header = (header or "").strip().lower()
        if header.startswith("["):
            host, _, rest = header[1:].partition("]")
            host, port = "[" + host + "]", rest.lstrip(":")
        else:
            host, _, port = header.partition(":")
        return host in self.allowed_hosts and port == str(self.port)

    def origin_ok(self, origin):
        try:
            p = urllib.parse.urlsplit(origin)
        except ValueError:
            return False
        return p.scheme == "http" and self.host_ok(p.netloc)

    def is_paired(self, dev):
        return bool(dev) and dev in self.paired

    # -- live updates --

    def touch(self, soon=False):
        now = time.time()
        if soon and now - self.last_touch < 0.25:
            return
        self.last_touch = now
        with self.cond:
            self.version += 1
            self.cond.notify_all()

    def snapshot(self):
        with self.lock:
            jobs = [j.public() for j in self.jobs]
        return json.dumps({"jobs": jobs, "lan_on": self.lan_on}).encode()

    # -- queue --

    def add_job(self, job):
        with self.lock:
            job.id, self.next_id = self.next_id, self.next_id + 1
            self.jobs.append(job)
            finished = [j for j in self.jobs if j.status in ("done", "failed", "cancelled")]
            for j in finished[:-40]:
                self.jobs.remove(j)
        self.q.put(job)
        self.touch()
        return job.id

    def cancel_queued(self, jid):
        with self.lock:
            for j in self.jobs:
                if j.id == jid and j.status == "queued":
                    j.status, j.cancel = "cancelled", True
        self.touch()

    def worker(self):
        while True:
            job = self.q.get()
            if job.status != "queued":
                continue
            job.status = "running"
            self.current = job
            self.touch()
            try:
                code = self.run_download(job) if job.kind == "download" else job.fn(job)
                job.status = "done" if not code else "failed"
                if code and not job.error:
                    job.error = "Something failed - check the terminal for details."
            except KeyboardInterrupt:
                job.status = "cancelled"
                print("\n[web] Job cancelled.")
            except Exception as e:
                job.status, job.error = "failed", short_error(e)
                print(f"\n[web] Error: {job.error}")
            finally:
                job.pct = None
                self.current = None
                self.touch()

    def run_download(self, job):
        if job.quality == "mp3":
            opts = mp3_options(job.playlist, job.items)
        else:
            opts = video_options(job.quality, job.playlist, job.items)
        print(f"\n[web] Job {job.id}: {job.label}")
        return run(job.url, opts, tap=self.make_tap(job))

    def make_tap(self, job):
        """Progress hooks that mirror yt-dlp's progress on the web page (and honor Ctrl+C cancel)."""
        def tap(kind, d):
            if job.cancel:
                raise KeyboardInterrupt
            if kind == "post":
                if d.get("postprocessor") == "MoveFiles" and d.get("status") == "finished":
                    job.done, job.pct, job.phase = job.done + 1, 100, "saved"
                    self.touch()
                elif d.get("status") == "started":
                    job.phase = "converting"
                    self.touch(soon=True)
                return
            if d.get("status") not in ("downloading", "finished"):
                return
            info = d.get("info_dict") or {}
            job.title = info.get("title") or job.title
            job.idx = info.get("playlist_index") or job.idx
            job.n = info.get("n_entries") or info.get("playlist_count") or job.total or job.n
            if d["status"] == "finished":
                job.phase = "processing"
            else:
                got = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                frac = got / total if total else None
                if frac is None and d.get("fragment_count"):
                    frac = (d.get("fragment_index") or 0) / d["fragment_count"]
                job.pct = round(min(max(frac, 0.0), 1.0) * 100, 1) if frac is not None else None
                job.speed = f"{fmt_size(d['speed'])}/s" if d.get("speed") else ""
                job.eta = fmt_eta(d["eta"]) if d.get("eta") is not None else ""
                job.phase = "downloading"
            self.touch(soon=True)
        return tap

    def add_task(self, label, fn):
        return self.add_job(Job("task", label, fn=fn))

    # -- LAN: pairing, approval, auto-off --

    def try_pin(self, ip, pin):
        """Returns (ok, message, retry_seconds). Wrong PINs are rate limited per device and overall."""
        now = time.time()
        with self.lock:
            rec = self.fails.setdefault(ip, [0, 0.0])
            if now < rec[1]:
                return False, "Too many wrong PINs. Wait a bit and try again.", int(rec[1] - now)
            if hmac.compare_digest(str(pin).encode("utf-8", "ignore"), self.pin.encode()):
                rec[0] = 0
                return True, "", 0
            rec[0] += 1
            if rec[0] >= 5:
                rec[0], rec[1] = 0, now + 300
            self.global_fails = [t for t in self.global_fails if now - t < 600] + [now]
            if len(self.global_fails) >= 10:          # someone is guessing: new PIN, old guesses are useless
                self.global_fails = []
                self.pin = self.new_pin()
                print(f"\n[lan] Several wrong PINs in a row. New PIN: {self.pin}")
            return False, "Wrong PIN.", 0

    def request_approval(self, ip):
        rid = secrets.token_urlsafe(12)
        req = {"ip": ip, "state": "waiting", "t": time.time()}
        with self.lock:
            self.pending[rid] = req
        self.approvals.put(req)
        return rid

    def approver(self):
        """Asks in the terminal, one device at a time."""
        while True:
            req = self.approvals.get()
            if req["state"] != "waiting" or time.time() - req["t"] > 120 or not self.lan_on:
                req["state"] = "denied"
                continue
            print(f"\n{req['ip']} wants to connect. Allow? [y/N] ", end="", flush=True)
            try:
                ans = input().strip().lower()
            except (EOFError, OSError):
                ans = "n"
            if req["state"] == "waiting":
                req["state"] = "allowed" if ans in ("y", "yes") else "denied"
            print(f"[lan] {req['ip']}: {'allowed' if req['state'] == 'allowed' else 'denied'}")

    def approval_status(self, rid, ip):
        with self.lock:
            req = self.pending.get(rid)
            if not req or req["ip"] != ip:
                return None, None
            if req["state"] == "waiting" and time.time() - req["t"] > 120:
                req["state"] = "denied"
            state = req["state"]
            if state == "allowed":
                dev = secrets.token_urlsafe(24)
                self.paired.add(dev)
                self.last_lan = time.time()
                del self.pending[rid]
                return state, dev
            if state == "denied":
                del self.pending[rid]
            return state, None

    def watchdog(self):
        while not self.stopping:
            time.sleep(15)
            if self.lan_on and self.lan_timeout > 0 and time.time() - self.last_lan > self.lan_timeout * 60:
                self.lan_on = False
                self.paired.clear()
                print(f"\n[lan] No activity for {self.lan_timeout} minutes: LAN access is now OFF. "
                      "Restart with --lan to turn it on again.")
                self.touch()

    # -- desktop player --

    def stop_audio(self):
        proc, self.audio_proc = self.audio_proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass


# --- the HTTP handler ---

class WebHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SnagIt"
    sys_version = ""
    timeout = 120

    def log_message(self, *args):
        pass

    def is_local_client(self):
        ip = self.client_address[0]
        return ip in ("127.0.0.1", "::1") or ip.startswith("::ffff:127.")

    def do_GET(self): self._handle()
    def do_HEAD(self): self._handle()
    def do_POST(self): self._handle()

    # -- responses --

    def _send(self, code, body, ctype, extra=(), cache="no-store"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", WEB_CSP)
        if code >= 400:
            self.send_header("Connection", "close")
            self.close_connection = True
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _text(self, code, msg):
        self._send(code, msg.encode(), "text/plain; charset=utf-8")

    def _json(self, obj, code=200, extra=()):
        self._send(code, json.dumps(obj).encode(), "application/json", extra)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > 1_000_000:
            raise ApiError("Bad request size", 413)
        raw = self.rfile.read(n) if n else b""
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise ApiError("Invalid JSON")
        if not isinstance(data, dict):
            raise ApiError("Invalid JSON")
        return data

    # -- the gate: host, origin, token, LAN pairing --

    def _handle(self):
        app = APP
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path, method = parsed.path, self.command
            self.local = self.is_local_client()
            if not app.host_ok(self.headers.get("Host", "")):
                return self._text(403, "Blocked: unexpected Host header.")
            origin = self.headers.get("Origin")
            if origin is not None and not app.origin_ok(origin):
                return self._text(403, "Blocked: cross-site request.")
            if method == "POST":
                if origin is None and self.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                    return self._text(403, "Blocked: cross-site request.")
                if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                    return self._text(415, "Expected JSON.")
            if not self.local and not app.lan_on:
                return self._text(403, "LAN access is off.")

            qs = urllib.parse.parse_qs(parsed.query)
            cookies = http.cookies.SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except http.cookies.CookieError:
                pass
            cookie = lambda name: cookies[name].value if name in cookies else ""
            tq = (qs.get("t") or [""])[0]
            if tq and app.token_ok(tq):
                if method == "GET" and path in ("/", "/check"):     # set the cookie, then hide the token
                    rest = urllib.parse.urlencode([(k, v) for k in qs if k != "t" for v in qs[k]])
                    self.send_response(302)
                    self.send_header("Location", path + ("?" + rest if rest else ""))
                    self.send_header("Set-Cookie", f"snagit_t={app.token}; Path=/; HttpOnly; SameSite=Strict")
                    self.send_header("Content-Length", "0")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                    return
            elif not app.token_ok(cookie("snagit_t")):
                return self._text(403, "Missing or wrong token. Open the link printed in the terminal.")

            if not self.local:
                if not app.is_paired(cookie("snagit_d")):
                    return self._unpaired(method, path, qs)
                if path not in QUIET_PATHS:
                    app.last_lan = time.time()
            self._route(method, path, qs)
        except ApiError as e:
            self._json({"error": str(e)}, e.code)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            self.close_connection = True
        except Exception as e:
            try:
                self._json({"error": short_error(e)}, 500)
            except OSError:
                self.close_connection = True

    def _unpaired(self, method, path, qs):
        app = APP
        ip = self.client_address[0]
        if method == "GET" and path in ("/", "/check"):
            return self._send(200, PAIR_HTML.encode(), "text/html; charset=utf-8")
        if method == "GET" and path == "/app.css":
            return self._send(200, APP_CSS.encode(), "text/css; charset=utf-8")
        if method == "GET" and path == "/pair.js":
            return self._send(200, PAIR_JS.encode(), "application/javascript; charset=utf-8")
        if method == "POST" and path == "/pair":
            data = self._body()
            ok, msg, wait = app.try_pin(ip, data.get("pin", ""))
            if not ok:
                return self._json({"error": msg, "retry": wait}, 429 if wait else 403)
            return self._json({"pending": app.request_approval(ip)})
        if method == "GET" and path == "/pair/status":
            state, dev = app.approval_status((qs.get("id") or [""])[0], ip)
            extra = ()
            if dev:
                extra = [("Set-Cookie", f"snagit_d={dev}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000")]
            return self._json({"state": state or "denied"}, 200, extra)
        self._json({"error": "This device isn't paired yet."}, 401)

    # -- routes --

    def _route(self, method, path, qs):
        app = APP
        arg = lambda name, default="": (qs.get(name) or [default])[0]
        if method in ("GET", "HEAD"):
            if path in ("/", "/check"):
                return self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
            if path == "/app.js":
                return self._send(200, APP_JS.encode(), "application/javascript; charset=utf-8")
            if path == "/app.css":
                return self._send(200, APP_CSS.encode(), "text/css; charset=utf-8")
            if path.startswith("/files/"):
                return self._file(path[len("/files/"):], arg("dl") == "1")
            if path == "/api/events":
                return self._events()
            if path == "/api/state":
                cfg = load_config()
                players = available_players()
                return self._json({
                    "version": VERSION, "local": self.local, "start_view": app.start_view,
                    "lan": {"enabled": app.lan, "on": app.lan_on},
                    "config": {"watch": cfg.get("web_watch", "browser"),
                               "player": pick_default_player(players), "players": players},
                    "qualities": list(QUALITIES), "default_quality": DEFAULT_QUALITY,
                    "output_dir": OUTPUT_DIR, "has_ytdlp": HAS_YTDLP})
            if path == "/api/lookup":
                return self._json(web_lookup(arg("q")))
            if path == "/api/search":
                q = arg("q").strip()
                if not q:
                    raise ApiError("Empty search")
                return self._json(web_search(q, max(0, min(int(arg("offset", "0") or 0), SEARCH_MAX))))
            if path == "/api/playlist":
                url = safe_http_url(arg("url"))
                if not url:
                    raise ApiError("Only http/https links are accepted.")
                return self._json(web_playlist(url, max(1, int(arg("start", "1") or 1))))
            if path == "/api/downloads":
                return self._json({"files": list_downloads()})
            if path == "/api/check":
                return self._json(web_check_data(app))
        elif method == "POST":
            return self._post(path, self._body())
        self._text(404, "Not found")

    def _need_local(self):
        if not self.local:
            raise ApiError("This can only be done from the computer running SnagIt.", 403)

    def _post(self, path, d):
        app = APP
        if path == "/api/download":
            need_ytdlp()
            url = safe_http_url(d.get("url"))
            if not url:
                raise ApiError("Only http/https links are accepted.")
            quality = str(d.get("quality") or DEFAULT_QUALITY)
            if quality != "mp3" and quality not in QUALITIES:
                raise ApiError("Unknown quality.")
            label = CONTROL_RE.sub(" ", str(d.get("title") or url))[:120]
            playlist, items, total = d.get("kind") == "playlist", None, None
            if playlist and not d.get("all"):
                try:
                    nums = [int(n) for n in d.get("indices") or []]
                except (TypeError, ValueError):
                    raise ApiError("Bad selection.")
                if not nums or len(nums) > 50000 or min(nums) < 1:
                    raise ApiError("Nothing selected.")
                items = compress_indices(nums)
                total = len(set(nums))
                if not valid_range(items):
                    raise ApiError("Bad selection.")
                label = f"{label} ({total} selected)"
            elif playlist:
                label += " (all)"
            jid = app.add_job(Job("download", label, url, quality, playlist, items, total))
            return self._json({"id": jid})
        if path == "/api/cancel":
            app.cancel_queued(int(d.get("id") or 0))
            return self._json({"ok": True})
        if path == "/api/stream":
            need_ytdlp()
            url = safe_http_url(d.get("url"))
            if not url:
                raise ApiError("Only http/https links are accepted.")
            q = str(d.get("quality") or DEFAULT_QUALITY)
            title, video_url, _ = resolve_stream(url, q if q in QUALITIES else DEFAULT_QUALITY,
                                                 False, bool(d.get("audio")))
            return self._json({"title": title, "url": video_url})
        if path == "/api/play":
            self._need_local()
            need_ytdlp()
            url = safe_http_url(d.get("url"))
            if not url:
                raise ApiError("Only http/https links are accepted.")
            audio = bool(d.get("audio"))
            names = available_players()
            name = pick_default_player(names)
            exe = find_player(name) if name else None
            if not exe:
                raise ApiError("No media player found. Install VLC or mpv, or use the browser player.", 503)
            q = str(d.get("quality") or DEFAULT_QUALITY)
            dual = PLAYER_SPECS.get(name, {}).get("dual", False)
            title, video_url, audio_url = resolve_stream(url, q if q in QUALITIES else DEFAULT_QUALITY, dual, audio)
            if audio:
                app.stop_audio()
            proc = launch_detached(build_player_cmd(name, exe, title, video_url, audio_url, audio))
            if audio:
                app.audio_proc = proc
            return self._json({"ok": True, "player": name, "title": title})
        if path == "/api/config":
            self._need_local()
            cfg = load_config()
            if "watch" in d:
                if d["watch"] not in ("browser", "desktop"):
                    raise ApiError("Unknown setting.")
                cfg["web_watch"] = d["watch"]
            if "player" in d:
                if d["player"] not in available_players():
                    raise ApiError("That player isn't installed.")
                cfg["player"] = d["player"]
            save_config(cfg)
            return self._json({"ok": True})
        if path == "/api/action":
            self._need_local()
            name = d.get("name")
            if name == "update":
                return self._json({"id": app.add_task("Update yt-dlp", task_update_ytdlp)})
            if name == "deno":
                return self._json({"id": app.add_task("Install Deno", task_install_deno)})
            raise ApiError("Unknown action.")
        if path == "/api/test":
            need_ytdlp()
            t0 = time.time()
            try:
                title, _, _ = resolve_stream(WEB_TEST_URL, "360", False, False)
                return self._json({"ok": True, "title": title, "secs": round(time.time() - t0, 1)})
            except Exception as e:
                return self._json({"ok": False, "error": short_error(e)})
        self._text(404, "Not found")

    # -- server-sent events --

    def _events(self):
        app = APP
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", WEB_CSP)
        self.end_headers()
        self.close_connection = True
        last = -1
        try:
            while not app.stopping:
                with app.cond:
                    if app.version == last:
                        app.cond.wait(15)
                    ver = app.version
                if not self.local and not app.lan_on:
                    return
                if ver != last:
                    self.wfile.write(b"data: " + app.snapshot() + b"\n\n")
                    last = ver
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:
            pass

    # -- files (path-traversal safe, with Range so audio/video can seek) --

    def _file(self, rel, as_download):
        full = resolve_download_path(rel)
        if not full:
            return self._text(404, "Not found")
        size = os.path.getsize(full)
        ext = os.path.splitext(full)[1].lower()
        ctype = EXTRA_MIME.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
        extra = [("Accept-Ranges", "bytes")]
        if as_download:
            name = os.path.basename(full)
            ascii_name = re.sub(r'[^A-Za-z0-9._ -]', "_", name)
            extra.append(("Content-Disposition",
                          f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name)}"))
        rng = parse_byte_range(self.headers.get("Range"), size)
        if rng == "bad":
            return self._send(416, b"", ctype, extra + [("Content-Range", f"bytes */{size}")])
        code, start, end = (200, 0, size - 1) if rng is None else (206, rng[0], rng[1])
        if code == 206:
            extra.append(("Content-Range", f"bytes {start}-{end}/{size}"))
        length = max(end - start + 1, 0)
        self.send_response(code)
        for k, v in [("Content-Type", ctype), ("Content-Length", str(length)), ("Cache-Control", "private, no-cache"),
                     ("X-Content-Type-Options", "nosniff"), ("Content-Security-Policy", "sandbox")] + extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD" or not length:
            return
        try:
            with open(full, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            self.close_connection = True


class WebServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# --- tasks that run in the terminal through the same queue ---

def task_update_ytdlp(job):
    print("\n[web] Updating yt-dlp...\n")
    code = subprocess.call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"])
    if code == 0:
        job.note = "Updated. Restart snagit --web to use the new version."
        print("\n[web] yt-dlp updated. Restart snagit --web to use it.\n")
    return code


def task_install_deno(job):
    print("\n[web] Installing Deno...\n")
    offer_js_install(ask=False)          # same logic as the terminal menu, just without input()
    if find_js_runtime()[0]:
        return 0
    job.error = "Not detected yet. If the installer finished, open a new terminal and run snagit again."
    return 1


# --- starting everything ---

def print_lan_info(app):
    ip = app.lan_ips[0] if app.lan_ips else None
    print("  " + "=" * 60)
    print("  WARNING: LAN mode is ON. Anyone on this network can reach the page.")
    print("  They still need the link's token, the PIN, and your approval here.")
    print("  " + "=" * 60)
    if not ip:
        print("  Couldn't work out this computer's network address.\n")
        return
    url = f"http://{ip}:{app.port}/?t={app.token}"
    print(f"  Network: {url}")
    print(f"  PIN:     {app.pin}   (a new device enters this once)")
    print(f"  Auto-off after {app.lan_timeout} idle minutes." if app.lan_timeout > 0 else "  Auto-off is disabled.")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except Exception:
        pass    # qrcode is optional (pip install qrcode); the address above works fine
    if not sys.stdin.isatty():
        print("  Note: no interactive terminal, so new devices can't be approved.")
    print()


def web_main(args):
    global VERBOSE, OUTPUT_DIR, APP
    VERBOSE = args.verbose
    if args.output:
        OUTPUT_DIR = os.path.abspath(os.path.expanduser(args.output))
    if not HAS_YTDLP and not args.check:
        sys.exit("yt-dlp is required. Install it: pip install -U \"yt-dlp[default]\"  "
                 "(or run snagit --web --check to install it from the browser)")
    if HAS_YTDLP:
        check_requirements(verbose=False)
    port = args.port or WEB_PORT
    lan_timeout = WEB_LAN_TIMEOUT if args.lan_timeout is None else args.lan_timeout
    APP = app = WebApp(port, args.lan, lan_timeout, "check" if args.check else "home")
    try:
        httpd = WebServer(("0.0.0.0" if args.lan else "127.0.0.1", port), WebHandler)
    except OSError as e:
        sys.exit(f"snagit: can't use port {port} ({e.strerror or e}). Is SnagIt already running? Try --port N")

    threading.Thread(target=app.worker, daemon=True).start()
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True).start()
    if args.lan:
        threading.Thread(target=app.approver, daemon=True).start()
        threading.Thread(target=app.watchdog, daemon=True).start()

    local_url = f"http://localhost:{port}/{'check' if args.check else ''}?t={app.token}"
    print(f"\n  SnagIt web {VERSION}")
    print(f"  Open:  {local_url}")
    print(f"  Saving to: {OUTPUT_DIR}")
    print("  Ctrl+C cancels the running download. Press it twice quickly (or when idle) to quit.\n")
    if args.lan:
        print_lan_info(app)
    if not args.no_open:
        try:
            webbrowser.open(local_url)
        except Exception:
            pass

    last_int = 0.0
    while True:
        try:
            time.sleep(0.5)
        except KeyboardInterrupt:
            now, cur = time.time(), app.current
            if cur is not None and now - last_int > 2:
                cur.cancel, last_int = True, now
                print("\n[web] Cancelling the current job... (Ctrl+C again within 2 seconds quits SnagIt)")
                app.touch()
                continue
            break
    print("\nStopping SnagIt web. Bye.")
    app.stopping = True
    app.stop_audio()
    httpd.shutdown()
    httpd.server_close()
    return 0


# ---------- web front end (plain HTML/CSS/JS, served from memory: no build step, no CDN) ----------

INDEX_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>SnagIt</title><link rel="stylesheet" href="/app.css"></head>
<body>
<header>
  <h1>SnagIt</h1>
  <nav id="nav">
    <button data-view="home" class="on">Home</button>
    <button data-view="queue">Queue <span id="badge" class="badge" hidden></span></button>
    <button data-view="dl">Downloads</button>
    <button data-view="check">Requirements</button>
    <button data-view="set">Settings</button>
  </nav>
</header>
<main>
<section id="v-home">
  <div class="box">
    <input id="box" type="text" autocomplete="off" spellcheck="false" autofocus
           placeholder="Paste a YouTube link, a playlist link, or type what to search for">
    <button id="paste" title="Paste from clipboard">Paste</button>
    <button id="go" class="pri">Go</button>
  </div>
  <p class="muted small">Playlist link gives a checklist. Video link gives one card. Anything else is a YouTube search.
    You can also press Ctrl+V anywhere or drop a link on this page.</p>
  <div class="row small"><label>Quality for Download buttons
    <select id="q"></select></label></div>
  <div id="out"></div>
</section>
<section id="v-queue" hidden><h2>Download queue</h2>
  <p class="muted small">One download runs at a time, in the terminal where <code>snagit --web</code> is running.
    Closing this tab does not stop anything. Ctrl+C in the terminal cancels the current job.</p>
  <div id="jobs"></div></section>
<section id="v-dl" hidden><h2>Downloads</h2>
  <div class="row"><input id="filter" type="search" placeholder="Filter files">
    <button id="playall">Play all audio</button><button id="refresh">Refresh</button></div>
  <p class="muted small" id="dlnote"></p><div id="files"></div></section>
<section id="v-check" hidden><h2>Requirements</h2>
  <div id="checks"><p class="muted">Checking...</p></div>
  <div class="row"><button id="recheck">Check again</button>
    <button id="upd">Update yt-dlp</button><button id="deno">Install Deno</button>
    <button id="test" class="pri">Test</button></div>
  <p id="testout" class="small"></p><div id="lanbox"></div></section>
<section id="v-set" hidden><h2>Settings</h2>
  <fieldset><legend>Watch and Audio buttons play in</legend>
    <label><input type="radio" name="watch" value="browser"> This page (browser)</label>
    <label><input type="radio" name="watch" value="desktop"> A desktop player on the computer (VLC / mpv)</label>
    <label>Desktop player <select id="player"></select></label>
    <p class="muted small" id="setnote"></p></fieldset>
  <p class="muted small" id="about"></p></section>
</main>
<div id="dock" hidden>
  <video id="vid" controls playsinline hidden></video>
  <div class="dockbar"><div class="now" id="now">Nothing playing</div>
    <audio id="aud" controls></audio>
    <button id="skip">Skip</button><button id="stop">Stop</button></div>
  <details id="qwrap"><summary id="qsum">Next up (0)</summary><div id="qlist"></div>
    <button id="qclear" class="small">Clear list</button></details>
</div>
<div id="toast" role="status"></div>
<script src="/app.js" defer></script>
</body></html>
"""

PAIR_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>SnagIt - connect</title><link rel="stylesheet" href="/app.css"></head>
<body><main class="pair"><h1>SnagIt</h1>
<p>Enter the 6-digit PIN shown in the terminal on the computer. Then approve this device there.</p>
<div class="box"><input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="123456">
<button id="go" class="pri">Connect</button></div>
<p id="msg" class="small"></p></main>
<script src="/pair.js" defer></script></body></html>
"""

PAIR_JS = r"""
"use strict";
const pin = document.getElementById("pin"), msg = document.getElementById("msg"), go = document.getElementById("go");
async function poll(id) {
  for (;;) {
    await new Promise(r => setTimeout(r, 1500));
    let d = {};
    try { d = await (await fetch("/pair/status?id=" + encodeURIComponent(id))).json(); } catch (e) { continue; }
    if (d.state === "allowed") { location.reload(); return; }
    if (d.state === "denied") { msg.textContent = "The computer said no, or nobody answered in time."; go.disabled = false; return; }
  }
}
go.addEventListener("click", async () => {
  go.disabled = true; msg.textContent = "";
  try {
    const r = await fetch("/pair", { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ pin: pin.value.trim() }) });
    const d = await r.json();
    if (!r.ok) { msg.textContent = d.error || "Failed."; go.disabled = false; return; }
    msg.textContent = "Waiting for approval on the computer...";
    poll(d.pending);
  } catch (e) { msg.textContent = "Can't reach the computer."; go.disabled = false; }
});
pin.addEventListener("keydown", e => { if (e.key === "Enter") go.click(); });
"""

APP_CSS = r"""
:root{--bg:#fff;--fg:#1b1b21;--mut:#6a6a76;--card:#f3f3f7;--line:#d9d9e1;--acc:#0b8fb3;--acc2:#c22a9c;--ok:#188a45;--bad:#c93636;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#141418;--fg:#ececf1;--mut:#9a9aa8;--card:#1f1f26;--line:#34343e;--acc:#35c7ea;--acc2:#ff4fd0;--ok:#43c777;--bad:#ff6b6b}}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding-bottom:5.5rem}
header{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem 1.2rem;padding:.7rem 1rem;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:5}
h1{margin:0;font-size:1.4rem;background:linear-gradient(90deg,var(--acc),var(--acc2));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{margin:.2rem 0 .6rem}h3{margin:0;font-size:1rem;overflow-wrap:anywhere}
nav{display:flex;flex-wrap:wrap;gap:.3rem}
main{max-width:980px;margin:0 auto;padding:1rem}
button,select,input[type=text],input[type=search],input:not([type]){font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.45rem .75rem}
button{cursor:pointer}button:hover{border-color:var(--acc)}button:disabled{opacity:.5;cursor:default}
button.on{border-color:var(--acc);color:var(--acc)}button.pri{background:var(--acc);border-color:var(--acc);color:#04222b;font-weight:600}
code{background:var(--card);padding:.1rem .3rem;border-radius:4px}
.box{display:flex;gap:.5rem}.box input{flex:1;min-width:0}
.row{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.5rem 0}
.muted{color:var(--mut)}.small{font-size:.85rem}.err{color:var(--bad)}.ok{color:var(--ok)}
.badge{background:var(--acc2);color:#fff;border-radius:99px;padding:0 .45rem;font-size:.75rem}
.card{display:flex;gap:.8rem;padding:.6rem;margin:.6rem 0;background:var(--card);border-radius:10px}
.card img{width:168px;height:94px;object-fit:cover;border-radius:6px;flex:none;background:var(--line)}
.info{min-width:0;flex:1}.btns{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.5rem}.btns button{padding:.3rem .6rem}
.tools{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin:.6rem 0;position:sticky;top:3.4rem;background:var(--bg);padding:.4rem 0;z-index:4}
.tools .grow{flex:1;min-width:8rem}
.pl{display:flex;gap:.6rem;align-items:center;padding:.35rem .4rem;border-bottom:1px solid var(--line);user-select:none;cursor:pointer}
.pl:hover{background:var(--card)}.pl img{width:80px;height:45px;object-fit:cover;border-radius:4px;flex:none;background:var(--line)}
.pl .n{width:2.6rem;text-align:right;color:var(--mut);flex:none;font-variant-numeric:tabular-nums}
.pl .t{flex:1;min-width:0;overflow-wrap:anywhere}.pl .d{color:var(--mut);flex:none}
.job{padding:.6rem;margin:.5rem 0;background:var(--card);border-radius:10px}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin:.4rem 0}.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--acc),var(--acc2))}
.pill{font-size:.75rem;border:1px solid var(--line);border-radius:99px;padding:0 .5rem;margin-left:.4rem}
.chk{display:flex;gap:.6rem;align-items:baseline;padding:.3rem 0;border-bottom:1px solid var(--line)}
.chk b{min-width:5.5rem;font-family:ui-monospace,monospace}.file{display:flex;flex-wrap:wrap;gap:.4rem .8rem;align-items:center;padding:.4rem 0;border-bottom:1px solid var(--line)}
.file .nm{flex:1;min-width:12rem;overflow-wrap:anywhere}.file a,.file button{font-size:.85rem}
a{color:var(--acc)}
fieldset{border:1px solid var(--line);border-radius:10px;display:grid;gap:.5rem}
#dock{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:.5rem .8rem;z-index:9}
#vid{width:100%;max-height:45vh;background:#000;border-radius:8px}
.dockbar{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}.now{flex:1 1 12rem;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
#aud{flex:2 1 14rem;height:36px;min-width:0}
#qlist .qi{display:flex;gap:.4rem;align-items:center;padding:.2rem 0}#qlist .qi span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#toast{position:fixed;left:50%;bottom:6rem;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:.5rem 1rem;border-radius:8px;opacity:0;pointer-events:none;transition:opacity .2s;max-width:90vw;z-index:20}
#toast.show{opacity:1}#toast.bad{background:var(--bad);color:#fff}
.pair{max-width:26rem;margin:15vh auto 0}.pair input{font-size:1.4rem;letter-spacing:.3rem;text-align:center}
@media (max-width:600px){.card{flex-direction:column}.card img{width:100%;height:auto;aspect-ratio:16/9}main{padding:.7rem}}
"""

APP_JS = r"""
"use strict";
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
function h(tag, a, ...kids) {
  const e = document.createElement(tag);
  for (const k in a || {}) {
    const v = a[k];
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) { if (c == null || c === false) continue; e.append(c.nodeType ? c : document.createTextNode(c)); }
  return e;
}
const S = { cfg: { watch: "browser", player: "", players: [] }, local: true, quals: [], dq: "720", jobs: [], files: [], lan: {} };
let toastT;
function toast(msg, bad) { const t = $("#toast"); t.textContent = msg; t.className = "show" + (bad ? " bad" : ""); clearTimeout(toastT); toastT = setTimeout(() => t.className = "", 3800); }
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  let d = {}; try { d = await r.json(); } catch (e) {}
  if (!r.ok || d.error) throw new Error(d.error || ("HTTP " + r.status));
  return d;
}
const pad = n => String(n).padStart(2, "0");
const fmtDur = s => { if (!s) return "--:--"; s = Math.floor(s); const H = Math.floor(s / 3600), M = Math.floor(s % 3600 / 60), X = s % 60; return H ? `${H}:${pad(M)}:${pad(X)}` : `${M}:${pad(X)}`; };
const fmtViews = n => { if (n == null) return ""; for (const [d, x] of [[1e9, "B"], [1e6, "M"], [1e3, "K"]]) if (n >= d) return (n / d).toFixed(1).replace(".0", "") + x + " views"; return n + " views"; };
const fmtSize = n => { for (const u of ["B", "KB", "MB", "GB"]) { if (n < 1024 || u === "GB") return (u === "B" ? n : n.toFixed(1)) + " " + u; n /= 1024; } };
const thumb = id => "https://i.ytimg.com/vi/" + encodeURIComponent(id) + "/mqdefault.jpg";
const encPath = p => p.split("/").map(encodeURIComponent).join("/");

// ---------- views ----------
function show(v) {
  for (const s of $$("main > section")) s.hidden = s.id !== "v-" + v;
  for (const b of $$("#nav button")) b.classList.toggle("on", b.dataset.view === v);
  try { history.replaceState(null, "", v === "check" ? "/check" : "/"); } catch (e) {}
  if (v === "dl") loadFiles();
  if (v === "check") loadCheck();
  if (v === "set") renderSettings();
}
for (const b of $$("#nav button")) b.addEventListener("click", () => show(b.dataset.view));

// ---------- the one box ----------
let seq = 0;
async function go(text) {
  text = (text || "").trim(); if (!text) return;
  $("#box").value = text; show("home");
  const out = $("#out"), my = ++seq;
  out.replaceChildren(h("p", { class: "muted" }, "Looking..."));
  try {
    const d = await api("/api/lookup?q=" + encodeURIComponent(text));
    if (my !== seq) return;
    if (d.kind === "search") renderSearch(d);
    else if (d.kind === "playlist") renderPlaylist(d);
    else out.replaceChildren(card(d.item));
  } catch (e) { if (my === seq) out.replaceChildren(h("p", { class: "err" }, e.message)); }
}
$("#go").addEventListener("click", () => go($("#box").value));
$("#box").addEventListener("keydown", e => { if (e.key === "Enter") go(e.target.value); });
$("#box").addEventListener("paste", () => setTimeout(() => { if (/^https?:\/\//i.test($("#box").value.trim())) go($("#box").value); }, 0));
$("#paste").addEventListener("click", async () => {
  try { const t = await navigator.clipboard.readText(); t ? go(t) : toast("The clipboard is empty."); }
  catch (e) { $("#box").focus(); toast("Can't read the clipboard here. Paste into the box instead (long-press on a phone).", true); }
});
document.addEventListener("paste", e => {
  const t = e.target; if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  const txt = e.clipboardData && e.clipboardData.getData("text"); if (txt) { e.preventDefault(); go(txt); }
});
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => {
  e.preventDefault(); const dt = e.dataTransfer; if (!dt) return;
  const raw = dt.getData("text/uri-list") || dt.getData("text/plain") || "";
  const line = raw.split(/\r?\n/).find(l => l.trim() && !l.startsWith("#")); if (line) go(line);
});

// ---------- cards ----------
async function queueDownload(body, label) {
  try { const d = await api("/api/download", body); toast(`Queued as job #${d.id}${label ? ": " + label : ""}. It runs in the terminal.`); }
  catch (e) { toast(e.message, true); }
}
const dlVideo = (it, q) => queueDownload({ kind: "video", url: it.url, quality: q, title: it.title }, it.title);
function card(it) {
  const meta = [it.channel, it.live ? "LIVE" : fmtDur(it.duration), fmtViews(it.views)].filter(Boolean).join(" | ");
  const b = (t, f, title) => h("button", { onclick: f, title }, t);
  return h("article", { class: "card" },
    h("img", { src: thumb(it.id), alt: "", loading: "lazy", referrerpolicy: "no-referrer", onerror: e => e.target.style.visibility = "hidden" }),
    h("div", { class: "info" }, h("h3", {}, it.title), h("div", { class: "muted small" }, meta),
      h("div", { class: "btns" },
        b("Watch", () => play(it, false)), b("Audio", () => play(it, true)),
        b("Download", () => dlVideo(it, $("#q").value)), b("MP3", () => dlVideo(it, "mp3")),
        b("+ Queue", () => addQ(trackOf(it), false), "Add to the Next up list"),
        b("Next", () => addQ(trackOf(it), true), "Play next"))));
}
function renderSearch(d) {
  const out = $("#out"), list = h("div"), more = h("button", {}, "Load more");
  let offset = 0;
  const add = r => { offset += r.items.length; r.items.forEach(it => list.append(card(it))); more.hidden = !r.more || !r.items.length;
    if (!offset) list.append(h("p", { class: "muted" }, "No results.")); };
  more.addEventListener("click", async () => {
    more.disabled = true;
    try { add(await api(`/api/search?q=${encodeURIComponent(d.query)}&offset=${offset}`)); } catch (e) { toast(e.message, true); }
    more.disabled = false;
  });
  out.replaceChildren(h("p", { class: "muted small" }, `Results for "${d.query}"`), list, more); add(d);
}

// ---------- playlist ----------
function parseRange(t, total) {
  t = t.replace(/\s+/g, "");
  if (!/^\d+(-\d+)?(,\d+(-\d+)?)*$/.test(t)) return null;
  const out = new Set();
  for (const p of t.split(",")) {
    let a, b;
    if (p.includes("-")) { [a, b] = p.split("-").map(Number); } else { a = b = Number(p); }
    if (a < 1 || b < a || b - a > 100000) return null;
    for (let k = a, hi = total ? Math.min(b, total) : b; k <= hi; k++) out.add(k);
  }
  return out;
}
function renderPlaylist(d) {
  const pl = { url: d.url, total: d.count || null, sel: new Set(), last: null, all: false, more: d.has_more, next: 1 };
  const list = h("div"), moreBtn = h("button", {}, "Load more");
  const qsel = h("select", {}, ...[...S.quals, "mp3"].map(q => h("option", { value: q }, q === "mp3" ? "MP3 (audio)" : q + "p")));
  qsel.value = $("#q").value;
  const cnt = h("strong", {}, "0 selected"), rng = h("input", { type: "text", class: "grow", placeholder: "Range, e.g. 1-5,8,10-12" });
  const boxes = new Map();
  const upd = () => { cnt.textContent = pl.all && !pl.total && pl.more ? "All selected" : pl.sel.size + " selected"; };
  const sync = () => { for (const [i, cb] of boxes) cb.checked = pl.sel.has(i); upd(); };
  const rows = items => items.forEach(it => {
    const cb = h("input", { type: "checkbox" }); cb.checked = pl.sel.has(it.index); boxes.set(it.index, cb);
    cb.addEventListener("click", ev => {
      pl.all = false;
      if (ev.shiftKey && pl.last != null) { const a = Math.min(pl.last, it.index), z = Math.max(pl.last, it.index);
        for (let k = a; k <= z; k++) cb.checked ? pl.sel.add(k) : pl.sel.delete(k); sync(); }
      else cb.checked ? pl.sel.add(it.index) : pl.sel.delete(it.index);
      pl.last = it.index; upd();
    });
    list.append(h("label", { class: "pl" }, cb, h("span", { class: "n" }, it.index),
      h("img", { src: thumb(it.id), alt: "", loading: "lazy", referrerpolicy: "no-referrer", onerror: e => e.target.style.visibility = "hidden" }),
      h("span", { class: "t" }, it.title), h("span", { class: "d" }, fmtDur(it.duration))));
    pl.next = it.index + 1;
  });
  const selectAll = () => {
    pl.sel = new Set(); pl.all = true;
    if (pl.total) for (let k = 1; k <= pl.total; k++) pl.sel.add(k); else for (const i of boxes.keys()) pl.sel.add(i);
    sync();
  };
  const load = r => { rows(r.items); pl.more = r.has_more; if (r.count) pl.total = r.count; moreBtn.hidden = !pl.more;
    if (pl.all && !pl.total) for (const i of boxes.keys()) pl.sel.add(i); sync(); };
  moreBtn.addEventListener("click", async () => {
    moreBtn.disabled = true;
    try { load(await api(`/api/playlist?url=${encodeURIComponent(pl.url)}&start=${pl.next}`)); } catch (e) { toast(e.message, true); }
    moreBtn.disabled = false;
  });
  const apply = () => { const s = parseRange(rng.value, pl.total); if (!s) { toast("Use a range like 1-5,8,10-12", true); return; }
    pl.sel = s; pl.all = false; sync(); };
  rng.addEventListener("keydown", e => { if (e.key === "Enter") apply(); });
  const dlBtn = h("button", { class: "pri", onclick: () => {
    if (!pl.sel.size && !pl.all) return toast("Tick at least one video first.", true);
    const body = { kind: "playlist", url: pl.url, quality: qsel.value, title: d.title };
    if (pl.all && !pl.total && pl.more) body.all = true; else body.indices = [...pl.sel];
    queueDownload(body, d.title);
  } }, "Download");
  $("#out").replaceChildren(
    h("h2", {}, d.title), h("p", { class: "muted small" }, (pl.total ? pl.total + " videos" : "Playlist") + ". Shift-click selects a range."),
    h("div", { class: "tools" }, qsel, h("button", { onclick: selectAll }, "Select all"),
      h("button", { onclick: () => { pl.sel = new Set(); pl.all = false; sync(); } }, "Select none"),
      rng, h("button", { onclick: apply }, "Tick range"), cnt, dlBtn),
    list, moreBtn);
  rows(d.items); moreBtn.hidden = !pl.more; upd();
}

// ---------- queue page (live via server-sent events) ----------
function renderJobs() {
  const jobs = S.jobs.slice().reverse(), active = S.jobs.filter(j => j.status === "queued" || j.status === "running").length;
  const badge = $("#badge"); badge.hidden = !active; badge.textContent = active;
  const box = $("#jobs");
  if (!jobs.length) return box.replaceChildren(h("p", { class: "muted" }, "Nothing queued yet."));
  box.replaceChildren(...jobs.map(j => {
    const bar = h("i"); if (j.pct != null) bar.style.width = j.pct + "%"; else if (j.status === "done") bar.style.width = "100%";
    const line = j.status === "running"
      ? [j.idx && j.n ? `[${j.idx}/${j.n}] ` : "", j.title || "", j.pct != null ? `  ${j.pct}%` : "", j.speed ? `  ${j.speed}` : "", j.eta ? `  ETA ${j.eta}` : "", j.phase && j.phase !== "downloading" ? `  (${j.phase})` : ""].join("")
      : j.status === "done" ? (j.done ? `${j.done} saved` : "Finished") + (j.note ? ". " + j.note : "") : j.error || "";
    return h("div", { class: "job" }, h("div", {}, h("strong", {}, `#${j.id} ${j.label}`), h("span", { class: "pill" }, j.status === "running" ? "running" : j.status),
      j.status === "queued" ? h("button", { class: "small", onclick: () => api("/api/cancel", { id: j.id }) }, "Remove") : null),
      h("div", { class: "bar" }, bar), h("div", { class: "muted small" }, line));
  }));
}
let prevStatus = {};
function onJobs(jobs) {
  for (const j of jobs) { const p = prevStatus[j.id];
    if (p && p !== j.status && j.status === "done") toast(`Finished: ${j.label}`);
    if (p && p !== j.status && j.status === "failed") toast(`Failed: ${j.label}`, true);
    prevStatus[j.id] = j.status; }
  S.jobs = jobs; renderJobs();
}
function listen() {
  const es = new EventSource("/api/events");
  es.onmessage = e => { const d = JSON.parse(e.data); onJobs(d.jobs); };
  es.onerror = () => { if (es.readyState === 2) setTimeout(listen, 5000); };
}

// ---------- player dock + "next up" list ----------
const P = { q: [], now: null };
try { P.q = JSON.parse(localStorage.getItem("snagit_q") || "[]").filter(t => t && t.title); } catch (e) {}
const trackOf = (it, audio = true) => ({ title: it.title, url: it.url, audio });
function saveQ() { try { localStorage.setItem("snagit_q", JSON.stringify(P.q)); } catch (e) {} }
function renderDock() {
  const has = P.now || P.q.length; $("#dock").hidden = !has;
  $("#now").textContent = P.now ? P.now.title : "Nothing playing";
  $("#qsum").textContent = `Next up (${P.q.length})`;
  $("#qlist").replaceChildren(...P.q.map((t, i) => h("div", { class: "qi" }, h("span", {}, `${i + 1}. ${t.title}`),
    h("button", { onclick: () => { P.q.splice(i, 1); saveQ(); renderDock(); start(t); } }, "Play"),
    h("button", { onclick: () => { P.q.splice(i, 1); saveQ(); renderDock(); } }, "x"))));
  $("#qclear").hidden = !P.q.length;
}
function addQ(t, front) {
  front ? P.q.unshift(t) : P.q.push(t); saveQ(); renderDock();
  toast(front ? "Playing next" : "Added to Next up");
  if (!P.now) next();
}
function stopMedia() { for (const el of [$("#aud"), $("#vid")]) { el.pause(); el.removeAttribute("src"); el.load(); } }
async function start(t) {
  P.now = t; renderDock(); stopMedia();
  const el = t.audio ? $("#aud") : $("#vid"); $("#vid").hidden = t.audio;
  $("#now").textContent = "Loading: " + t.title;
  try {
    el.src = t.src || (await api("/api/stream", { url: t.url, audio: t.audio, quality: $("#q").value })).url;
    $("#now").textContent = t.title; await el.play();
  } catch (e) { if (P.now === t) { toast("Couldn't play that: " + e.message, true); renderDock(); } }
}
function next() {
  if (P.q.length) { const t = P.q.shift(); saveQ(); start(t); }
  else { P.now = null; stopMedia(); $("#vid").hidden = true; renderDock(); }
}
for (const el of [$("#aud"), $("#vid")]) {
  el.addEventListener("ended", next);
  el.addEventListener("error", () => { if (P.now && el.getAttribute("src")) { toast("This one won't play in the browser. Skipping.", true); next(); } });
}
$("#skip").addEventListener("click", next);
$("#stop").addEventListener("click", () => { P.q.length = 0; saveQ(); next(); });
$("#qclear").addEventListener("click", () => { P.q.length = 0; saveQ(); renderDock(); });
async function play(it, audio) {
  if (S.cfg.watch === "desktop" && S.local) {
    try { const d = await api("/api/play", { url: it.url, audio, quality: $("#q").value }); toast(`Playing in ${d.player}`); }
    catch (e) { toast(e.message, true); }
  } else start(trackOf(it, audio));
}

// ---------- downloads page ----------
async function loadFiles() {
  try { S.files = (await api("/api/downloads")).files; renderFiles(); } catch (e) { $("#files").replaceChildren(h("p", { class: "err" }, e.message)); }
}
const fileTrack = f => ({ title: f.name.replace(/\.[^.]+$/, ""), src: "/files/" + encPath(f.path), audio: f.audio });
function renderFiles() {
  const q = $("#filter").value.trim().toLowerCase(), list = S.files.filter(f => !q || f.path.toLowerCase().includes(q));
  $("#dlnote").textContent = `${list.length} file(s). Saved in ${S.output_dir || ""}`;
  $("#files").replaceChildren(...list.map(f => h("div", { class: "file" },
    h("div", { class: "nm" }, f.folder ? h("span", { class: "muted" }, f.folder + " / ") : null, f.name),
    h("span", { class: "muted small" }, fmtSize(f.size)),
    h("button", { onclick: () => start(fileTrack(f)) }, "Play"),
    f.audio ? h("button", { onclick: () => addQ(fileTrack(f), false) }, "+ Queue") : null,
    h("a", { href: "/files/" + encPath(f.path) + "?dl=1", download: f.name }, "Save"))));
  if (!list.length) $("#files").replaceChildren(h("p", { class: "muted" }, "No finished files yet."));
}
$("#filter").addEventListener("input", renderFiles);
$("#refresh").addEventListener("click", loadFiles);
$("#playall").addEventListener("click", () => {
  const a = S.files.filter(f => f.audio && (!$("#filter").value || f.path.toLowerCase().includes($("#filter").value.toLowerCase())));
  if (!a.length) return toast("No audio files to play.", true);
  a.forEach(f => P.q.push(fileTrack(f))); saveQ(); renderDock(); if (!P.now) next();
});

// ---------- requirements page ----------
async function loadCheck() {
  const box = $("#checks"); box.replaceChildren(h("p", { class: "muted" }, "Checking..."));
  try {
    const d = await api("/api/check");
    box.replaceChildren(...d.checks.map(c => h("div", { class: "chk" }, h("b", { class: c.ok ? "ok" : "err" }, c.ok ? "[ALRIGHT]" : "[JACK]"),
      h("span", {}, c.label, c.detail ? h("span", { class: "muted" }, "  " + c.detail) : null, !c.ok ? h("div", { class: "muted small" }, "-> " + c.fix) : null))));
    const lb = $("#lanbox"); lb.replaceChildren();
    if (d.lan) lb.append(h("h3", {}, "LAN mode"),
      h("p", { class: "small" }, d.lan.on ? "On. " : "Off (idle timeout reached). ", d.lan.address ? "Address: " + d.lan.address + " (use the full link with the token from the terminal). " : "",
        "Anyone on your network can reach the page, but they need the token, the PIN and your approval."),
      h("p", { class: "muted small" }, "Firewall: " + d.lan.firewall));
  } catch (e) { box.replaceChildren(h("p", { class: "err" }, e.message)); }
}
$("#recheck").addEventListener("click", loadCheck);
$("#test").addEventListener("click", async () => {
  const out = $("#testout"); out.className = "small muted"; out.textContent = "Testing a short video...";
  try { const d = await api("/api/test", {});
    out.className = "small " + (d.ok ? "ok" : "err");
    out.textContent = d.ok ? `Works. Resolved "${d.title}" in ${d.secs}s.` : "Failed: " + d.error;
  } catch (e) { out.className = "small err"; out.textContent = e.message; }
});
for (const [id, name] of [["upd", "update"], ["deno", "deno"]]) $("#" + id).addEventListener("click", async () => {
  try { const d = await api("/api/action", { name }); toast(`Started as job #${d.id}. Watch the terminal.`); show("queue"); }
  catch (e) { toast(e.message, true); }
});

// ---------- settings ----------
function renderSettings() {
  const c = S.cfg, ps = $("#player");
  for (const r of $$("input[name=watch]")) { r.checked = r.value === c.watch; r.disabled = !S.local && r.value === "desktop"; }
  ps.replaceChildren(...(c.players.length ? c.players.map(p => h("option", { value: p }, p)) : [h("option", { value: "" }, "none found")]));
  ps.value = c.player || ""; ps.disabled = !S.local || !c.players.length;
  $("#setnote").textContent = !S.local ? "Desktop players can only be chosen on the computer itself. This device uses the browser player."
    : c.players.length ? "Saved automatically." : "No VLC or mpv found, so the browser player is used.";
  $("#about").textContent = `SnagIt ${S.version}. Files are saved in ${S.output_dir}.`;
}
for (const r of $$("input[name=watch]")) r.addEventListener("change", async () => {
  try { await api("/api/config", { watch: r.value }); S.cfg.watch = r.value; toast("Saved"); } catch (e) { toast(e.message, true); renderSettings(); }
});
$("#player").addEventListener("change", async e => {
  try { await api("/api/config", { player: e.target.value }); S.cfg.player = e.target.value; toast("Saved"); } catch (er) { toast(er.message, true); }
});

// ---------- start ----------
(async function init() {
  try {
    const st = await api("/api/state");
    Object.assign(S, { cfg: st.config, local: st.local, quals: st.qualities, dq: st.default_quality, version: st.version, output_dir: st.output_dir });
    if (!S.local) S.cfg.watch = "browser";
    $("#q").replaceChildren(...S.quals.map(q => h("option", { value: q }, q + "p"))); $("#q").value = S.dq;
    if (!st.has_ytdlp) toast("yt-dlp is missing. Open Requirements and press Update yt-dlp.", true);
    renderDock(); renderJobs(); listen();
    show(location.pathname === "/check" || st.start_view === "check" ? "check" : "home");
  } catch (e) { $("#out").replaceChildren(h("p", { class: "err" }, "Can't reach SnagIt: " + e.message)); }
})();
"""


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
               "  snagit -s lofi -P mpv -q 1080  same, using mpv at 1080p\n"
               "  snagit -s song name -a -f      play the top result as audio only, no list\n"
               "  snagit -s song name -a         browse results, Enter plays just the audio\n"
               "  snagit --web                   local web interface (paste a link or type a search)\n"
               "  snagit --web --check           web interface, straight to the requirements page\n"
               "  snagit --web --lan             also reachable from a phone on the same Wi-Fi\n\n"
               f"made by Echo404 - Twitter: {TWITTER}\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("url", nargs="?", help="video or playlist link (asked for if omitted)")
    p.add_argument("-q", "--quality", choices=QUALITIES, metavar="{" + ",".join(QUALITIES) + "}",
                   help=f"video quality in p (default: {DEFAULT_QUALITY})")
    p.add_argument("-p", "--playlist", action="store_true",
                   help="treat the link as a playlist (default: single video)")
    p.add_argument("-a", "--audio", action="store_true",
                   help="audio only, converted to MP3 (combine with -p for a playlist); "
                        "with -s: play audio only, no video")
    p.add_argument("-r", "--range", type=range_arg, metavar="RANGE",
                   help='playlist items to get, e.g. 1-5,8,10-12 (default: all; needs -p)')
    p.add_argument("-o", "--output", metavar="DIR",
                   help=f"output folder (default: {OUTPUT_DIR})")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show full yt-dlp output (default: clean progress only)")
    p.add_argument("-s", "--search", nargs="+", metavar="TEXT",
                   help="search YouTube and browse the results (Enter = watch, d = download)")
    p.add_argument("-f", "--first", action="store_true",
                   help="with -s: skip the list and play the top result right away")
    p.add_argument("-P", "--player", metavar="NAME",
                   help="player for search mode: vlc, mpv, iina, ffplay, or any command/path "
                        "(default: last one used, else the first one found)")
    p.add_argument("-T", "--no-thumbs", action="store_true",
                   help="search mode: don't show thumbnails")
    p.add_argument("-i", "--interactive", action="store_true",
                   help="force the interactive menu")
    p.add_argument("--web", action="store_true",
                   help=f"start the local web interface (http://localhost:{WEB_PORT}/)")
    p.add_argument("--port", type=int, metavar="N", help=f"with --web: fixed port (default: {WEB_PORT})")
    p.add_argument("--no-open", action="store_true", help="with --web: don't open the browser automatically")
    p.add_argument("--check", action="store_true", help="with --web: open straight to the requirements page")
    p.add_argument("--lan", action="store_true",
                   help="with --web: also listen on the local network (phone on the same Wi-Fi). "
                        "Needs a PIN and your approval for each device")
    p.add_argument("--lan-timeout", type=int, metavar="M",
                   help=f"with --lan: turn LAN access off after M idle minutes (default: {WEB_LAN_TIMEOUT}, 0 = never)")
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
    parser = build_parser()
    args = parser.parse_args()
    if args.first and args.search is None:
        parser.error("-f/--first needs -s/--search")
    web_only = [n for n, v in (("--port", args.port), ("--no-open", args.no_open), ("--check", args.check),
                               ("--lan", args.lan), ("--lan-timeout", args.lan_timeout)) if v]
    if web_only and not args.web:
        parser.error(f"{', '.join(web_only)} need --web")
    if args.lan_timeout is not None and not args.lan:
        parser.error("--lan-timeout needs --lan")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.lan_timeout is not None and args.lan_timeout < 0:
        parser.error("--lan-timeout can't be negative")
    if args.web:
        if args.url or args.search is not None or args.interactive:
            parser.error("--web can't be combined with a link, -s or -i")
        sys.exit(web_main(args))
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
