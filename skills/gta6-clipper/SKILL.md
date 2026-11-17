---
name: gta6-clipper
description: GTA 6 stream clipper for Windows, for VODs and live streams (--live records Twitch/YouTube channels and clips chat and loudness spikes as they happen). Finds the biggest GTA 6 streams (YouTube, Twitch, Kick), listens to the whole stream on the GPU, has Claude pick the most viral moments in two passes (candidates, then a side-by-side "viral editor" re-rank), and renders 1-2 minute 9:16 clips that cover the whole topic, in one fixed house style (streamer on top, a constant boxless title with one yellow keyword on the seam, the game below fixed on the centre of the stream, short natural-case word-pop captions), cover.jpg, plus a POST.md with title, description and hashtags per clip. Optional FilmCraft polish pass. Use whenever the user wants to clip GTA 6 (or GTA) streams, make Shorts/TikToks/Reels from a stream VOD, "clip this stream", "find today's biggest GTA 6 streams", or polish a clip.
---

# GTA 6 Clipper

Streams in, ready-to-post vertical clips out, always in the **house style** (`docs/house-style.md` in the plugin folder). **You run it; the user gives links (or nothing: `--find`).**
`PLUGIN` = `${CLAUDE_PLUGIN_ROOT}`. The command is `"${CLAUDE_PLUGIN_ROOT}\gta6clip.cmd"` (PowerShell: `& "$env:CLAUDE_PLUGIN_ROOT\gta6clip.cmd"`).
Output: `%USERPROFILE%\gta6-clips\<date>\<streamer>__<title>\` — `NN_<name>.mp4`, `NN_<name>_cover.jpg`, `POST.md`, `clips.json`, `report.json`.

## 0. First use on this PC
1. Run `powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}\setup.ps1"` until it prints **All set** (checks ffmpeg with NVENC + libass, Claude Code, node, uv; builds `%USERPROFILE%\.gta6-clipper\venv`; downloads fonts, YuNet, Whisper `small` + `large-v3-turbo` ≈ 2 GB). Run it in the background; tell the user what it's doing.
2. `claude -p` must be logged in (picking runs on the user's subscription). If a run logs `OAuth session expired`, ask the user to run `claude` once in a terminal and log in. Never type credentials yourself.
3. Narrated intro: **off** in the house style. Only if the user asks: `--voice voxcpm2` (VoiceStudio open; clones the VoiceStudio voice profile set as `voice_profile` in config.json) or `--voice kokoro`. Never OmniVoice (non-commercial).

## 1. Run it
Run long jobs in the background and report progress in plain words.
```
gta6clip.cmd URL                       # one stream, 3 clips
gta6clip.cmd URL URL --clips 4         # several streams
gta6clip.cmd --find --list             # show today's biggest GTA streams
gta6clip.cmd --find --streams 7        # find and clip them (~21 clips)
gta6clip.cmd URL --section "2:00:00-4:00:00"
```
| flag | use |
|---|---|
| `--clips N` | clips per stream (default 3); each 1-2 min covering the whole topic |
| `--bar N` | minimum viral score (default 70); a stream with nothing above it gets no clips and the log says the best score |
| `--cookies-file cookies.txt` | age-restricted YouTube (most GTA streams): a cookies.txt the user exported with "Get cookies.txt LOCALLY" from an **incognito** window they then closed (normal-window exports get rotated and stop working). Lives in the plugin folder, git-ignored, never shown or committed. `--cookies firefox` also works; Chrome's own cookies can't be read on Windows |
| `--voice voxcpm2/kokoro` | turn the narrated intro on (off by default) |
| `--section A-B` | only part of a stream; for live streams clip the new hours |
| `--layout stream/face/fit` | force a framing |
| `--model sonnet` | lighter Claude model for picking |
| `--redo` | pick again (keeps audio) · `--keep-audio` keep the stream audio |

Re-running the same command resumes from `%USERPROFILE%\gta6-clips\work\`.
Speed on this PC: listening ~1-2 min per stream hour (GPU), render ~1-2 min per clip (NVENC).

## 2. Finding streams
`--find` merges YouTube "today, most viewed, >20 min" for "GTA 6 stream", the watchlist `%USERPROFILE%\gta6-clips\streamers.txt` (`twitch:login`, `youtube:@handle`), and Twitch top live (only with `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET` in `gta6-clips\.env`). Before Nov 19 2026 it mostly finds GTA 5 streams.

## 2b. Live mode (clip while they are live)
`gta6clip.cmd --live twitch:kaicenat twitch:xqc youtube:@IShowSpeed [--for SECONDS] [--cookies-file cookies.txt]`
Run it in the background and leave it running; Ctrl+C or `--for` stops it. Per channel:
1. **Record**: Streamlink waits for the channel to go live and records `%USERPROFILE%\gta6-clips\recordings\<channel>\*.ts` (~3-6 GB/hour). A recording is deleted automatically once its session has ended and every spike in it is clipped; it is kept if any of its clips failed.
ecordings\<channel>\*.ts` (kept; ~3-6 GB/hour).
2. **Chat (Twitch)**: anonymous read-only IRC; 10 s buckets vs the previous 5 min mean, spike at 3x and >= 8 messages (5 min warm-up after going live).
3. **Loudness (Twitch + YouTube)**: +12 dB over the previous 5 min for >= 2 s. YouTube has no anonymous chat, so loudness is its trigger.
4. **Clip**: ~100 s after a spike, the window 75 s before / 90 s after is cut from the recording; Claude picks the whole topic and writes the title (fallback without `claude -p`: 45 s each side of the spike, title "<Streamer> *Can't* Believe This 😭"); rendered in the house style into `gta6-clips\<date>\<channel>__live\`, POST.md updated after every clip.
Recordings are deleted once their clips are done (kept only when a clip failed); tell the user when disk space runs low.

## 3. Launch-day playbook (GTA 6 unlocks Nov 19, 2026)
- Start `--live` on the biggest GTA streamers before they go online; it waits for them and clips as they react.
- The evening before, `--find --list` shows who streams GTA; add the regulars to the watchlist with the user.
- Backup for streams live mode missed: `--find --streams 7` every few hours. YouTube streams can only be fetched after they end; for a Twitch broadcast still running, `--section` from where the last run stopped (see `report.json`) clips only the new part.
- Speed matters most in the first hours (first look at the map, the first drive, the first chase): get those clips to the user first.

## 4. Before the user posts (always)
Look at each clip (extract frames at 3 s, the middle and the end with ffmpeg and view them): streamer face fills the top panel, the title is on the seam with exactly one yellow word, the game half shows the centre of the stream, captions are 1-3 words just under the title, no empty emoji boxes, the clip covers the whole topic (no mid-sentence cut).

## 5. FilmCraft polish (on request, for the clips the user marks)
For each marked clip, with the FilmCraft tools:
1. `media_import` the clip mp4 → new sequence 1080×1920 30 fps with it on V1/A1.
2. Tighten: trim any slow start/end (keep the whole topic and the payoff).
3. Extra punch-ins: on the payoff peak, scale 100→115 % over 6 frames, hold, ease back.
4. SFX from earshot: `sfx_list`, then `sfx_render` a whoosh/boom/record-scratch aimed at the peak; place on A2, −8 dB under voice; check with earshot `timeline`.
5. Branding if the user has it: watermark (top-left, 60 % opacity) and/or a 1 s end card.
6. Optional: the user's own voice-over on A3 replacing the narrator line.
7. `render_preview` to check, then export `<clip>_polished.mp4` next to the original. Never post.

## 6. Problems
| symptom | fix |
|---|---|
| "Sign in to confirm your age" / Kick 403 / cookie errors | export a fresh cookies.txt from an incognito window (see `--cookies-file`) |
| `claude -p failed: ... OAuth` | user runs `claude` and logs in |
| "couldn't line the clip up by sound" | the clip may be ~1 s off: `--redo` or check it |
| "no clip reached 70" | low-energy stream: try another, or `--bar 60` |
| "still live on YouTube" | wait for the stream to end, or use the streamer's Twitch VOD link |
| a line "voiced by Kokoro" | VoiceStudio closed or VoxCPM2 out of VRAM; open VoiceStudio and re-run (cached lines are retried) |
| GPU Whisper fell back to CPU | re-run setup.ps1 (CUDA libs) |
Settings: any key from `gta6clip/config.py` in `%USERPROFILE%\gta6-clips\config.json`.
