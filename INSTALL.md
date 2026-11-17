# Clipping Machine — install (Windows)

Turns GTA 6 streams (YouTube, Twitch, Kick, finished or **live**) into ready-to-post
9:16 Shorts / TikToks / Reels: streamer on top, game below, a constant title with one yellow
word, word-by-word captions, plus a POST.md with title, description and hashtags per clip.
Nothing is ever posted for you.

## You need
- Windows 10/11 with an **NVIDIA GPU** (for fast transcription and encoding)
- **Claude Code**, logged in (`claude` works in cmd) — it picks the moments
- **FFmpeg full build**: `winget install Gyan.FFmpeg`
- **uv**: `winget install astral-sh.uv`
- **Node.js**: `winget install OpenJS.NodeJS`
- ~3 GB free for models, plus space for clips (live recordings ~3-6 GB/hour while recording)

## Install
1. Clone (`git clone https://github.com/dev-parthdeshmukh/clipping-machine.git`) or unzip this
   repo somewhere permanent, e.g. `C:\Users\<you>\Desktop\clipping-machine`.
2. In cmd:
   ```
   claude plugin marketplace add "C:\Users\<you>\Desktop\clipping-machine"
   claude plugin install gta6-clipper@gta6-clipper-local
   ```
3. Open Claude Code and type **`/gta6-setup`**. It installs everything else (Python env,
   yt-dlp, Whisper, Streamlink, fonts) and prints **All set**. First run downloads ~2.5 GB.

## Use
| Type in Claude Code | What happens |
|---|---|
| `/gta6-find --list` | shows today's biggest GTA streams |
| `/gta6-clip <stream link>` | clips a finished stream |
| `/gta6-find` | finds the biggest streams and clips them |
| `/gta6-live twitch:kaicenat youtube:@IShowSpeed` | records them while live and clips the hype moments as they happen |
| `/gta6-polish <clip.mp4>` | optional polish in FilmCraft (sound effects, zooms) |

Clips land in `C:\Users\<you>\gta6-clips\<date>\<streamer>__<title>\`. Watch every clip
before posting, and only clip streamers who allow clipping.

## Age-restricted YouTube (most GTA streams)
1. Chrome → Extensions → install **Get cookies.txt LOCALLY** → allow it in Incognito.
2. Open an **Incognito** window, sign in to youtube.com, click the extension → **Export**.
3. Close the Incognito window. Save the file as `cookies.txt` in the plugin folder.
4. Runs then use `--cookies-file cookies.txt`.
This file is your YouTube login: never share or upload it.

## Optional
- Your streamer list: `C:\Users\<you>\gta6-clips\streamers.txt` (`twitch:name`, `youtube:@handle`).
- Settings (any key from `gta6clip\config.py`): `C:\Users\<you>\gta6-clips\config.json`.
- Narrated intro (off by default): `--voice kokoro` (free voice), or `--voice voxcpm2` with
  VoiceStudio and your own voice profile (`"voice_profile": "<your profile id>"` in config.json).
