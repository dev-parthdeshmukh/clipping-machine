# Clipping Machine

GTA 6 streams in, ready-to-post vertical clips out. Works on finished streams **and while
streamers are live**, on YouTube, Twitch and Kick. Runs as a Claude Code plugin on Windows.

Every clip comes out in one consistent style: streamer on top, the game below, a constant title
with one yellow keyword, word-by-word captions, and a `POST.md` with a title, description,
hashtags and captions for TikTok, Shorts and Reels. Nothing is ever posted for you.

## What it does
- Clips finished streams from a link, or finds today's biggest GTA streams by itself
- Records streamers the moment they go live and clips the hype as it happens
- Spots hype from Twitch chat speed (read anonymously, read-only) and from loudness spikes
- Transcribes on your NVIDIA GPU (Whisper)
- Picks the best moments in two passes with Claude Code (candidates, then a side-by-side re-rank)
- Makes 1-2 minute clips that cover the whole topic, never cut mid-sentence
- Cuts quiet dead air, encodes on the GPU at -14 LUFS, makes a cover image per clip
- Deletes live recordings once their clips are done
- Optional: narrated intro (Kokoro or your own VoiceStudio voice), FilmCraft polish pass

## Requirements
- Windows 10/11 with an NVIDIA GPU
- [Claude Code](https://claude.com/claude-code), logged in
- FFmpeg full build: `winget install Gyan.FFmpeg`
- uv: `winget install astral-sh.uv`
- Node.js: `winget install OpenJS.NodeJS`

## Install
```
git clone https://github.com/dev-parthdeshmukh/clipping-machine.git
claude plugin marketplace add "<path to clipping-machine>"
claude plugin install gta6-clipper@gta6-clipper-local
```
Then in Claude Code run `/gta6-setup` (installs the Python env, yt-dlp, Whisper, Streamlink and
fonts; the first run downloads about 2.5 GB). Full guide: [INSTALL.md](INSTALL.md).

## Use
| In Claude Code | What happens |
|---|---|
| `/gta6-find --list` | today's biggest GTA streams |
| `/gta6-clip <link>` | clip a finished stream |
| `/gta6-find` | find the biggest streams and clip them |
| `/gta6-live twitch:kaicenat youtube:@IShowSpeed` | record while live, clip spikes as they happen |
| `/gta6-polish <clip.mp4>` | optional polish in FilmCraft |

From a terminal: `gta6clip.cmd <link>`, `gta6clip.cmd --find`, `gta6clip.cmd --live twitch:<name>`.
Clips land in `%USERPROFILE%\gta6-clips\<date>\<streamer>__<title>\`.

Age-restricted YouTube streams need a `cookies.txt` (see INSTALL.md) passed with
`--cookies-file`. Keep that file private; git ignores it.

## Style
See [docs/house-style.md](docs/house-style.md). Settings live in
`%USERPROFILE%\gta6-clips\config.json` (any key from `gta6clip/config.py`).

## Tests
```
%USERPROFILE%\.gta6-clipper\venv\Scripts\python.exe -m pytest tests
```

## Be fair
Only clip streamers who allow clipping, credit them (POST.md includes a credit line), and follow
each platform's rules. Watch every clip before you post it.
