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
"""

import argparse
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    yt_dlp = None
    HAS_YTDLP = False

VERSION = "1.1.0"
TWITTER = "@JeffreyPeter_"
QUALITIES = ("360", "480", "720", "1080")
DEFAULT_QUALITY = "720"
# Saves to ~/Downloads/SnagIt (works on Windows, Linux and macOS)
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "SnagIt")
RANGE_RE = re.compile(r"^\d+(-\d+)?(,\d+(-\d+)?)*$")

# JS runtimes yt-dlp can use, in order of preference
JS_RUNTIMES = ("deno", "node", "bun")

OS = platform.system()  # "Windows", "Linux", "Darwin" (macOS)
DENO_BIN = os.path.join(os.path.expanduser("~"), ".deno", "bin")

JACK = "[JACK]"      # not installed
ALRIGHT = "[ALRIGHT]"  # installed

BANNER = r"""
  ____                    ___ _
 / ___| _ __   __ _  __ _|_ _| |_
 \___ \| '_ \ / _` |/ _` || || __|
  ___) | | | | (_| | (_| || || |_
 |____/|_| |_|\__,_|\__, |___|\__|
                    |___/
"""


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


def welcome():
    print(BANNER)
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


def run(url, opts):
    print("Snagging... \n")
    with yt_dlp.YoutubeDL(opts) as ydl:
        code = ydl.download([url])
    if code:
        print("\nSomething failed, check the messages above. Nothing (or not everything) was saved.")
    else:
        print(f"\nDone! Files saved in {OUTPUT_DIR}")
    return code


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


def interactive_main():
    welcome()
    while True:
        choice = ask_choice(
            "What do you want to snag?",
            [("playlist", "Playlist"), ("single", "Single video"), ("mp3", "MP3 (audio only)")],
        )
        try:
            {"playlist": flow_playlist, "single": flow_single, "mp3": flow_mp3}[choice]()
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
               "  snagit URL -a -p               whole playlist as MP3\n\n"
               f"Twitter: {TWITTER}\n",
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
    p.add_argument("-i", "--interactive", action="store_true",
                   help="force the interactive menu")
    p.add_argument("-V", "--version", action="version", version=f"SnagIt {VERSION}")
    return p


def cli_main(args):
    global OUTPUT_DIR
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
    if args.interactive or len(sys.argv) == 1:
        interactive_main()
    else:
        sys.exit(cli_main(args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBye.")
        sys.exit(130)
