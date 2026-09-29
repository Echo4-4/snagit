# SnagIt

A simple YouTube downloader by Echo404: playlist, single video, or MP3. It can search YouTube from the terminal, play videos in VLC or mpv, and run a local web interface you can also open from your phone.

Current version: **1.4.0**

## Requirements

* yt-dlp (includes the yt-dlp-ejs challenge solver): `pip install -U "yt-dlp[default]"`
* FFmpeg
* A JS runtime (deno, node or bun). YouTube needs one or some formats go missing.

For search & watch (optional):

* A media player: VLC or mpv (IINA and ffplay also work)
* Pillow, for thumbnails in the results list: `pip install Pillow`

For the web interface (optional):

* qrcode, to show a QR code in `--lan` mode: `pip install qrcode`

SnagIt checks your setup on start. In the terminal, missing items are shown as `[JACK]` and installed ones as `[ALRIGHT]`. The web interface has the same list on its Requirements page.

## Usage

```
snagit                       interactive menu
snagit "URL" -q 720          single video
snagit "URL" -p -r 1-5       playlist, items 1-5
snagit "URL" -a              MP3
snagit -s TEXT               search YouTube and watch
snagit -s song name -a -f    play the top result as audio only
snagit --web                 web interface
snagit --web --lan           web interface, also reachable from your phone
```

Files are saved to `~/Downloads/SnagIt` by default. Use `-o DIR` to change that.

Run `snagit -h` for all flags.

### Flags

| Flag | What it does |
| --- | --- |
| `-q 360/480/720/1080` | Video quality (default 720) |
| `-p`, `--playlist` | Treat the link as a playlist |
| `-a`, `--audio` | Download as MP3. With `-s`, play audio only |
| `-r RANGE` | Playlist items to get, e.g. `1-5,8,10-12` (needs `-p`) |
| `-o DIR` | Output folder |
| `-v` | Show full yt-dlp output instead of the clean progress bar |
| `-s TEXT` | Search YouTube |
| `-f`, `--first` | With `-s`: skip the list and play the top result |
| `-P NAME` | Player: `vlc`, `mpv`, `iina`, `ffplay`, or a path |
| `-T`, `--no-thumbs` | No thumbnails in the results list |
| `-i` | Force the interactive menu |
| `--web` | Start the web interface |
| `--port N` | With `--web`: use a different port (default 8642) |
| `--no-open` | With `--web`: don't open the browser |
| `--check` | With `--web`: open straight to the Requirements page |
| `--lan` | With `--web`: allow phones and other computers on your Wi-Fi |
| `--lan-timeout M` | With `--lan`: turn LAN access off after M idle minutes (default 30, 0 = never) |
| `-V` | Show the version |

## Interactive menu

Run `snagit` with no arguments. You can choose:

* Playlist
* Single video
* MP3 (audio only), from a single video or a playlist
* Search YouTube & watch

You also pick clean or verbose output, and SnagIt keeps asking what to snag next until you say no.

## Web interface

Start it on your own computer:

```
snagit --web
```

The terminal prints a link like `http://localhost:8642/?t=<token>` and your browser opens it. The token is random each run, so always use the link from the terminal. The page remembers it in a cookie after the first visit.

### Downloading

Paste a link or type text into the one box on the Home page. You can also press Ctrl+V anywhere, click Paste, or drag a link onto the page.

* A playlist link gives a checklist. Tick videos with the checkboxes (shift-click selects a range), use Select all / Select none, or type a range like `1-5,8,10-12` and press "Tick range". Pick a quality or MP3, then press Download.
* A single video link gives one video card.
* Anything else runs a YouTube search, 10 results at a time. Use "Load more" for the next batch.

On a video or search card, press Download (uses the quality picker on Home) or MP3.

Downloads run in the terminal with the usual progress bar, one job at a time. Extra clicks join the queue. Closing the tab doesn't stop anything.

Big playlists load 100 videos at a time. "Select all" still selects the whole playlist.

### Stopping

* `Ctrl+C` in the terminal cancels the current download.
* Press `Ctrl+C` twice within 2 seconds, or once when nothing is downloading, to quit SnagIt.

### The pages

| Page | What it does |
| --- | --- |
| Home | The one box, search results, playlist checklist, and video cards with Watch, Audio, Download, MP3, + Queue and Next |
| Queue | Live progress for every job: current video, percent, speed, ETA, and done or failed. You can remove jobs that haven't started |
| Downloads | Finished files from your output folder. Play them in the page, or press Save to download a copy. Has a filter box and "Play all audio". Seeking works |
| Requirements | The `[ALRIGHT]`/`[JACK]` list with versions. Buttons: Update yt-dlp and Install Deno (both run in the terminal), and Test, which resolves a short video and reports the result |
| Settings | Choose whether Watch and Audio play in the browser page or in VLC/mpv on the computer. Saved in your config file |

### Watch and Audio

* **Browser mode** plays inside the page, using a combined stream, usually up to 720p.
* **Desktop mode** opens VLC or mpv on the computer (computer only, not from a phone).
* **Next up:** the "+ Queue" and "Next" buttons build a music list at the bottom of the page. It plays automatically, and Skip moves to the next song.
* **Music player:** on the Downloads page, use Play on any file, or "Play all audio", to use the page as a home music player.

## Phone or another computer (`--lan`)

```
snagit --web --lan
```

Add `--lan-timeout 60` to change the idle auto-off (default 30 minutes, `0` means never).

### Connect a phone

1. The terminal prints a warning that anyone on the network can reach the page, then the address, a 6-digit PIN, and a QR code. The QR code only appears if you ran `pip install qrcode`. Without it, type the printed address.
2. On the phone, scan the QR code or open the address.
3. Enter the PIN once.
4. The terminal asks `<ip> wants to connect. Allow? [y/N]`. Type `y`.
5. The phone is paired for 30 days.

### What the phone can do

* **Share to computer:** copy a YouTube link on the phone, paste it in the one box, and the download runs on the computer.
* **Save to phone:** on the Downloads page, press Save on a finished file.
* **Stream music:** on the Downloads page, press Play, or use "Play all audio".
* Phones can't launch a desktop player, run Update yt-dlp or Install Deno, or change Settings. Those only work on the computer itself.

### Safety and limits

* A device needs the link's token, the PIN, and your approval in the terminal.
* Wrong PINs are rate-limited. After several guesses the PIN changes and the terminal prints the new one.
* After the idle timeout, LAN access switches off and paired devices are cleared. Restart with `--lan` to turn it back on. The computer's own browser keeps working either way.
* To turn LAN off yourself, quit SnagIt with Ctrl+C. Next time, start with just `--web`.

### Firewall

| System | What to do |
| --- | --- |
| Windows | Choose Allow when the firewall asks about Python |
| Linux | `sudo ufw allow 8642` (or your `--port`) |
| macOS | Choose Allow when asked about incoming connections |

The Requirements page shows the LAN address and this hint while LAN mode is on.

### Web troubleshooting

| Problem | Fix |
| --- | --- |
| "Missing or wrong token" | Open the link printed in the terminal, not just `localhost:8642` |
| "Can't use port 8642" | SnagIt is probably already running. Close it or use `--port 9000` |
| Phone can't reach the page | Check that it's on the same Wi-Fi, the firewall allows the port, and LAN mode hasn't timed out |
| Videos won't play or download | Open Requirements and run Test. If something shows `[JACK]`, use its button or fix hint, then restart SnagIt after updating yt-dlp |

## Search & watch

Search YouTube without leaving the terminal. Results open full screen like `less`, with a small thumbnail next to each title, channel, length and view count. Scroll down and more results load automatically. Press Enter and the video opens online in your player.

```
snagit -s TEXT            search and browse
snagit -s TEXT -P mpv -q 1080     use mpv at 1080p
snagit -s TEXT -T                 no thumbnails
```

### Listen without the video

Add `-a` to play only the audio, and `-f` to skip the list and play the top result straight away:

```
snagit -s daft punk one more time -a -f    search and play the sound right away
snagit -s daft punk -a                     browse the list, Enter plays just the audio
```

With `-f` the song plays in your terminal session and stops when you press Ctrl+C. In the list, Enter plays one song at a time (picking another replaces it) and `s` stops it. Quitting the list stops the music too.

You can also pick **Search YouTube & watch** from the interactive menu.

### Keys

| Key | Action |
| --- | --- |
| Up / Down (or `k` / `j`) | Move through the list |
| PgUp / PgDn (or `b` / Space / `f`) | Page up / down |
| Home / End (or `g` / `G`) | Jump to first / last loaded result |
| Enter | Play the selected video (or just its audio in audio mode) |
| `a` | Switch between video and audio-only |
| `s` | Stop the audio started from the list |
| `p` | Switch player (your choice is remembered) |
| `u` | Change watch quality (360 / 480 / 720 / 1080) |
| `d` | Download the selected video |
| `m` | Download the selected video as MP3 |
| `/` | New search |
| `r` | Retry if loading results failed |
| `q` or Esc | Quit |

### Players

SnagIt looks for VLC, mpv, IINA and ffplay, including VLC's default install folders on Windows and macOS. Use `-P` to choose one, or to point at any other player:

```
snagit -s TEXT -P vlc
snagit -s TEXT -P "C:\path\to\player.exe"
```

VLC and mpv get separate video and audio streams, so they can play up to 1080p. Other players get a single combined stream, usually 720p or lower.

### Thumbnails

Thumbnails are drawn with colored block characters, so they work in any color terminal on Windows, Linux and macOS with no extra tools. They look best in terminals with truecolor support (Windows Terminal, iTerm2, most Linux terminals). macOS Terminal.app only has 256 colors, so they look rougher there. Without Pillow, or with `-T`, the list shows text only.

## Config

Your player choice and web Settings are saved in a small config file:

* Windows: `%APPDATA%\snagit\config.json`
* Linux and macOS: `~/.config/snagit/config.json` (or `$XDG_CONFIG_HOME/snagit/config.json`)

## Install as a command

Run this once from the folder containing `snagit.py`. After that you can use `snagit` from anywhere, without typing `python` or `./`.

```
git clone https://github.com/Echo4-4/snagit.git
cd snagit
chmod +x snagit.py
mkdir -p ~/.local/bin
cp snagit.py ~/.local/bin/snagit
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Using bash? Replace `~/.zshrc` with `~/.bashrc` in the last two lines.

Check that it works:

```
snagit -h
```

To update later, pull the latest changes and copy the file over again:

```
git pull
cp snagit.py ~/.local/bin/snagit
```

Twitter: @JeffreyPeter_
