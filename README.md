# SnagIt

A simple YouTube downloader by Echo404: playlist, single video, or MP3. It can also search YouTube from the terminal and play videos in VLC or mpv.

## Requirements

* yt-dlp: `pip install -U "yt-dlp[default]"`
* FFmpeg
* A JS runtime (deno, node or bun)

For search & watch (optional):

* A media player: VLC or mpv (IINA and ffplay also work)
* Pillow, for thumbnails in the results list: `pip install Pillow`

## Usage

```
snagit "URL" -q 720          single video
snagit "URL" -p -r 1-5       playlist, items 1-5
snagit "URL" -a              MP3
snagit -s lofi hip hop       search YouTube and watch
```

Run `snagit -h` for all flags.

## Search & watch

Search YouTube without leaving the terminal. Results open full screen like `less`, with a small thumbnail next to each title, channel, length and view count. Scroll down and more results load automatically. Press Enter and the video opens online in your player.

```
snagit -s lofi hip hop            search and browse
snagit -s lofi -P mpv -q 1080     use mpv at 1080p
snagit -s lofi -T                 no thumbnails
```

You can also pick **Search YouTube & watch** from the interactive menu (run `snagit` with no arguments).

### Keys

| Key | Action |
| --- | --- |
| Up / Down (or `k` / `j`) | Move through the list |
| PgUp / PgDn (or `b` / Space) | Page up / down |
| Home / End (or `g` / `G`) | Jump to first / last loaded result |
| Enter | Watch the selected video |
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
snagit -s lofi -P vlc
snagit -s lofi -P "C:\path\to\player.exe"
```

VLC and mpv get separate video and audio streams, so they can play up to 1080p. Other players get a single combined stream, usually 720p or lower.

### Thumbnails

Thumbnails are drawn with colored block characters, so they work in any color terminal on Windows, Linux and macOS with no extra tools. They look best in terminals with truecolor support (Windows Terminal, iTerm2, most Linux terminals). macOS Terminal.app only has 256 colors, so they look rougher there. Without Pillow, or with `-T`, the list shows text only.

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
