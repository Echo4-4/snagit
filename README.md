# SnagIt

A simple YouTube downloader by Echo404: playlist, single video, or MP3.

## Requirements
- yt-dlp: pip install -U "yt-dlp[default]"
- FFmpeg
- A JS runtime (deno, node or bun)

## Usage
snagit                       interactive menu
snagit "URL" -q 720          single video
snagit "URL" -p -r 1-5       playlist, items 1-5
snagit "URL" -a              MP3

Run snagit -h for all flags.

## Install as a command

Run this once from the folder containing `snagit.py`. After that you can use `snagit` from anywhere, without typing `python` or `./`.

```bash
git clone https://github.com/Echo4-4/snagit.git
cd snagit
chmod +x snagit.py
mkdir -p ~/.local/bin
cp snagit.py ~/.local/bin/snagit
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Using bash?** Replace `~/.zshrc` with `~/.bashrc` in the last two lines.

Check that it works:

```bash
snagit -h
```

To update later, pull the latest changes and copy the file over again:

```bash
git pull
cp snagit.py ~/.local/bin/snagit
```

Twitter: @JeffreyPeter_
